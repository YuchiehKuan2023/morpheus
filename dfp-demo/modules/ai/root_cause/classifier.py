#!/usr/bin/env python3
"""
Root Cause Classifier — Stage 2 of the AI Auto-Labeling Pipeline

Purpose
-------
Classify TRUE anomalies (is_anomaly=TRUE, set by Stage 1 AnomalyValidator) into
one of 9 fine-grained `sub_category` labels, then derive the coarse `root_cause`
from a static mapping.

Stage 1 answered: "Is this detection a real security event?"
Stage 2 answers:  "What kind of security event is this?"

Model
-----
DistilBERT (distilbert-base-uncased, 66M params):
    - 40 % smaller and 60 % faster than BERT-base with 97 % of its NLU accuracy
    - Encoder CLS token (768-dim) → Dropout(0.3) → Linear(768 → 9) → softmax
    - Pre-trained weights loaded from HuggingFace; classification head randomly
      initialised and fine-tuned on local anomaly data

Why DistilBERT and not a simpler model (LogReg, XGBoost)?
    The top_features string contains a mix of feature *names*, numeric *values*,
    and z-score *magnitudes*, e.g.
        "appdisplayname=Zoom=4.21, travel_speed_kmph=1843.50=9.87"
    This requires contextual understanding of which combinations of feature names
    co-occur (multi-factor vs. single-feature patterns) — a task well-suited to
    a pre-trained language model with attention, not a bag-of-words classifier.

Input Feature Text
------------------
Composed from two DB fields per record:
    "features: <raw_detection->>'top_features'> | score: <anomaly_score:.2f>"

Example:
    "features: appdisplayname=Zoom=4.21, locationcountry=FR=3.88,
               travel_speed_kmph=1843.50=9.87 | score: 14.32"

Classes (sub_category — 9 labels)
----------------------------------
    0  Impossible Travel
    1  Multi-Factor Anomaly
    2  Location with Unusual Device
    3  Unknown Device
    4  Unusual Application
    5  Unusual Location
    6  Unusual Browser
    7  Unusual Operating System
    8  Broad Deviation

Each sub_category maps to a coarse root_cause via ROOT_CAUSE_MAP (no second model).

Training Data
-------------
    SELECT anomaly_id, raw_detection->>'top_features', anomaly_score, sub_category,
           validation_confidence
    FROM enriched_anomalies
    WHERE is_anomaly = TRUE AND sub_category IS NOT NULL
    ORDER BY validation_confidence DESC

Confidence weighting is applied during training so that high-confidence labels
(0.90, validated_by='heuristic_score') dominate over low-confidence midband
placeholders (0.55, validated_by='heuristic_midband').  As LLM batch_labeler
overwrites midband records the effective training signal improves automatically.

Model Persistence
-----------------
    Saved to / loaded from: data/models/root_cause/
    Files:
        model_state.pt          — PyTorch state dict (weights only)
        config.json             — label mapping, hyperparameters, training metadata
    MLflow experiment: "root_cause_classifier" (logged by training.py)

Usage (inference)
-----------------
    >>> from modules.ai.root_cause.classifier import RootCauseClassifier
    >>> clf = RootCauseClassifier()
    >>> clf.load(model_dir="data/models/root_cause")
    >>>
    >>> result = clf.predict(
    ...     anomaly_id="uuid-...",
    ...     top_features="appdisplayname=Zoom=4.21, travel_speed_kmph=1843.50=9.87",
    ...     anomaly_score=14.32,
    ... )
    >>> print(result["sub_category"])      # "Impossible Travel"
    >>> print(result["root_cause"])        # "Geographic Anomaly"
    >>> print(result["confidence"])        # 0.94

    >>> batch = clf.predict_batch(records)  # list of dicts with same keys

Architecture Reference
----------------------
    docs/implementation/PROGRESS_TRACKER.md  (Week 11-14: Stage 2)
    docs/implementation/LABELING_FEEDBACK_ARCHITECTURE.md
    modules/ai/auto_labeling/anomaly_validator.py  (Stage 1)
    modules/ai/enrichment/persistence_service.py   (update_classification)
    modules/ai/root_cause/training.py              (fine-tuning loop)
    modules/ai/root_cause/labeling_worker.py       (periodic inference job)

Author: AI Intelligence Layer Team
Date: 2026-03-03
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

# ---------------------------------------------------------------------------
# Optional heavy dependencies.
#
# Pattern: import under TYPE_CHECKING so that Pylance/mypy see proper types
# for annotations; re-import at runtime inside try/except so TORCH_AVAILABLE
# reflects whether the packages are actually installed.
# With `from __future__ import annotations` all annotations are lazy strings,
# so the TYPE_CHECKING-only names are never evaluated at runtime.
# ---------------------------------------------------------------------------
if TYPE_CHECKING:
    import torch
    import torch.nn as nn
    from transformers import DistilBertModel, DistilBertTokenizerFast

try:
    import torch  # type: ignore[no-redef]
    import torch.nn as nn  # type: ignore[no-redef]
    from transformers import DistilBertModel, DistilBertTokenizerFast  # type: ignore[no-redef]

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label space — canonical order that must be preserved between training and
# inference (index i must always refer to the same class).
# ---------------------------------------------------------------------------

SUB_CATEGORY_LABELS: list[str] = [
    "Impossible Travel",  # 0
    "Multi-Factor Anomaly",  # 1
    "Location with Unusual Device",  # 2
    "Unknown Device",  # 3
    "Unusual Application",  # 4
    "Unusual Location",  # 5
    "Unusual Browser",  # 6
    "Unusual Operating System",  # 7
    "Broad Deviation",  # 8
]

NUM_LABELS = len(SUB_CATEGORY_LABELS)

# Coarse root_cause derived from sub_category — no second model needed.
#
# NOTE: "Account Takeover" has been intentionally REMOVED as a catch-all.
# "Multi-Factor Anomaly" and "Broad Deviation" are DistilBERT's fallback classes
# (predicted when no single dominant feature is identifiable).  Mapping these to
# "Account Takeover" caused ~80-90 % of all detections to carry that label,
# regardless of whether credential compromise was evidenced.
# "Multi-Factor Incident" and "Behavioral Anomaly" are neutral, accurate labels
# for multi-feature deviations until the model can be retrained with labelled data
# that properly distinguishes credential-based from non-credential deviations.
ROOT_CAUSE_MAP: dict[str, str] = {
    "Impossible Travel": "Geographic Anomaly",
    "Multi-Factor Anomaly": "Multi-Factor Incident",  # was "Account Takeover" — too alarming
    "Location with Unusual Device": "Geographic Anomaly",
    "Unknown Device": "Unmanaged Device",
    "Unusual Application": "Unauthorized Application Access",
    "Unusual Location": "Geographic Anomaly",
    "Unusual Browser": "Browser Anomaly",
    "Unusual Operating System": "OS Anomaly",
    "Broad Deviation": "Behavioral Anomaly",  # was "Account Takeover" — too alarming
}

# Default model directory (relative to project root)
DEFAULT_MODEL_DIR = Path("data/models/root_cause")

# DistilBERT checkpoint name (HuggingFace hub)
DISTILBERT_CHECKPOINT = "distilbert-base-uncased"

# Tokeniser limits
MAX_SEQ_LEN = 128  # top_features strings are short; 128 tokens is always sufficient


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ClassificationResult:
    """Result of a single root-cause inference."""

    anomaly_id: str
    sub_category: str
    root_cause: str
    confidence: float  # probability of the top predicted class
    reasoning: str  # human-readable justification
    raw_scores: dict[str, float]  # {sub_category: probability} for all 9 classes
    feature_text: str  # the composed input text (for debugging / audit)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# PyTorch model definition
# ---------------------------------------------------------------------------


def _build_model() -> nn.Module:
    """
    Build DistilBERT + classification head.

    Must only be called when TORCH_AVAILABLE is True.  Separated from the
    class so that training.py can import just this function without
    instantiating RootCauseClassifier.
    """
    if not TORCH_AVAILABLE:
        raise RuntimeError("torch and transformers are required. Install with: pip install torch transformers")

    class _DistilBertClassifier(nn.Module):
        """
        DistilBERT encoder with a single linear classification head.

        Architecture:
            DistilBERT (frozen or fine-tuned) → [CLS] token (768-dim)
            → Dropout(0.3)
            → Linear(768 → NUM_LABELS)
            → (softmax applied at inference time, not here)

        The dropout rate of 0.3 intentionally exceeds the DistilBERT-default
        of 0.1 to add regularisation for our small (~350 sample) training set.
        """

        def __init__(self, num_labels: int = NUM_LABELS, dropout: float = 0.3):
            super().__init__()
            self.distilbert = DistilBertModel.from_pretrained(DISTILBERT_CHECKPOINT, local_files_only=True)
            self.pre_classifier = nn.Linear(768, 768)
            self.dropout = nn.Dropout(dropout)
            self.classifier = nn.Linear(768, num_labels)
            self.relu = nn.ReLU()

        def forward(
            self,
            input_ids: torch.Tensor,
            attention_mask: torch.Tensor,
        ) -> torch.Tensor:
            """
            Forward pass.

            Args:
                input_ids:      (batch, seq_len) token IDs
                attention_mask: (batch, seq_len) 1/0 mask

            Returns:
                logits: (batch, num_labels) — raw scores before softmax
            """
            outputs = self.distilbert(
                input_ids=input_ids,
                attention_mask=attention_mask,
            )
            # [CLS] token is the first token of the last hidden state
            hidden_state = outputs.last_hidden_state  # (batch, seq_len, 768)
            cls_output = hidden_state[:, 0]  # (batch, 768)

            # Two-layer head with ReLU: mirrors the DistilBERT classification head
            # from the original paper for sequence classification tasks.
            pooled = self.pre_classifier(cls_output)  # (batch, 768)
            pooled = self.relu(pooled)
            pooled = self.dropout(pooled)
            logits = self.classifier(pooled)  # (batch, num_labels)

            return logits

    return _DistilBertClassifier()


# ---------------------------------------------------------------------------
# High-level inference API
# ---------------------------------------------------------------------------


class RootCauseClassifier:
    """
    High-level root cause classifier for TRUE anomaly detections.

    Wraps the DistilBERT model with:
        - Feature text composition  (top_features + anomaly_score → input string)
        - Tokenisation              (DistilBertTokenizerFast, max 128 tokens)
        - Inference                 (softmax over 9 classes)
        - Label decoding            (index → sub_category + root_cause mapping)
        - Model persistence         (save/load state dict + config.json)

    Typical lifecycle:
        1. training.py:        clf.save("data/models/root_cause/")
        2. labeling_worker.py: clf.load("data/models/root_cause/") → predict_batch()

    Thread safety:
        The model and tokeniser are read-only during inference; the class is
        safe to use from multiple threads as long as no training (weight updates)
        is happening concurrently.
    """

    def __init__(
        self,
        model_dir: str | Path | None = None,
        device: str | None = None,
    ):
        """
        Initialise the classifier.  Does NOT load model weights — call
        :meth:`load` explicitly (or let :meth:`predict` raise a clear error).

        Args:
            model_dir: Directory containing model_state.pt and config.json.
                       Defaults to DEFAULT_MODEL_DIR.  Can be overridden by the
                       ROOT_CAUSE_MODEL_DIR environment variable.
            device:    "cpu", "cuda", or "mps".  Auto-detected when None:
                       CUDA → MPS → CPU in priority order.
        """
        self.model_dir = Path(model_dir or os.getenv("ROOT_CAUSE_MODEL_DIR", str(DEFAULT_MODEL_DIR)))
        self.device = self._resolve_device(device)
        self._model: nn.Module | None = None
        self._tokeniser = None
        self._idx_to_label: dict[int, str] = dict(enumerate(SUB_CATEGORY_LABELS))
        self._label_to_idx: dict[str, int] = {lbl: idx for idx, lbl in enumerate(SUB_CATEGORY_LABELS)}
        self._training_metadata: dict[str, Any] = {}

        logger.info(f"RootCauseClassifier initialised (device={self.device}, model_dir={self.model_dir})")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def is_trained(self) -> bool:
        """True when model weights have been loaded / trained."""
        return self._model is not None

    def load(self, model_dir: str | Path | None = None) -> RootCauseClassifier:
        """
        Load model weights and config from disk.

        Args:
            model_dir: Override the model directory set at construction.

        Returns:
            self (for method chaining: clf.load().predict(...))

        Raises:
            FileNotFoundError: model_state.pt or config.json not found.
            RuntimeError:      torch / transformers not installed.
        """
        if not TORCH_AVAILABLE:
            raise RuntimeError("torch and transformers are required. Install with: pip install torch transformers")

        load_dir = Path(model_dir) if model_dir else self.model_dir
        state_path = load_dir / "model_state.pt"
        config_path = load_dir / "config.json"

        if not state_path.exists():
            raise FileNotFoundError(
                f"Model weights not found at {state_path}. Run training.py first to train and save the model."
            )
        if not config_path.exists():
            raise FileNotFoundError(
                f"Model config not found at {config_path}. The model directory appears incomplete — re-run training.py."
            )

        # Load config (label order is canonical but double-checked here)
        with open(config_path) as f:
            config = json.load(f)

        saved_labels = config.get("sub_category_labels", SUB_CATEGORY_LABELS)
        if saved_labels != SUB_CATEGORY_LABELS:
            logger.warning(
                "Saved label order differs from module constant SUB_CATEGORY_LABELS. "
                "Using saved order — ensure inference and training used the same version."
            )
        self._idx_to_label = dict(enumerate(saved_labels))
        self._label_to_idx = {lbl: idx for idx, lbl in enumerate(saved_labels)}
        self._training_metadata = config.get("training_metadata", {})

        # Build model architecture and load weights
        self._model = _build_model().to(self.device)
        state_dict = torch.load(state_path, map_location=self.device, weights_only=True)
        self._model.load_state_dict(state_dict)
        self._model.eval()

        # Load tokeniser (either cached locally alongside weights, or from HF hub)
        tokeniser_dir = load_dir / "tokeniser"
        if tokeniser_dir.exists():
            self._tokeniser = DistilBertTokenizerFast.from_pretrained(str(tokeniser_dir), local_files_only=True)
        else:
            self._tokeniser = DistilBertTokenizerFast.from_pretrained(DISTILBERT_CHECKPOINT, local_files_only=True)

        trained_at = self._training_metadata.get("trained_at", "unknown")
        best_val_acc = (
            self._training_metadata.get("best_val_accuracy") or self._training_metadata.get("val_accuracy") or "unknown"
        )
        best_val_f1 = (
            self._training_metadata.get("best_val_f1_macro") or self._training_metadata.get("val_f1_macro") or "unknown"
        )

        logger.info(
            f"Loaded RootCauseClassifier from {load_dir} "
            f"(trained: {trained_at}, "
            f"best_val_acc: {best_val_acc}, "
            f"best_val_f1_macro: {best_val_f1})"
        )
        return self

    def save(self, model_dir: str | Path | None = None) -> Path:
        """
        Save model weights, tokeniser, and config to disk.

        Called by training.py after fine-tuning completes.

        Args:
            model_dir: Directory to save into (default: self.model_dir).

        Returns:
            Path to saved directory.

        Raises:
            RuntimeError: Model has not been trained/loaded yet.
        """
        if self._model is None:
            raise RuntimeError("No model to save — train or load first.")

        save_dir = Path(model_dir) if model_dir else self.model_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        # Weights
        torch.save(self._model.state_dict(), save_dir / "model_state.pt")

        # Tokeniser
        tokeniser_dir = save_dir / "tokeniser"
        if self._tokeniser:
            self._tokeniser.save_pretrained(str(tokeniser_dir))

        # Config
        config = {
            "sub_category_labels": SUB_CATEGORY_LABELS,
            "root_cause_map": ROOT_CAUSE_MAP,
            "distilbert_checkpoint": DISTILBERT_CHECKPOINT,
            "max_seq_len": MAX_SEQ_LEN,
            "num_labels": NUM_LABELS,
            "training_metadata": self._training_metadata,
        }
        with open(save_dir / "config.json", "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"RootCauseClassifier saved to {save_dir}")
        return save_dir

    def predict(
        self,
        anomaly_id: str,
        top_features: str,
        anomaly_score: float,
    ) -> ClassificationResult:
        """
        Classify a single TRUE anomaly detection.

        Args:
            anomaly_id:    UUID from enriched_anomalies.
            top_features:  Raw top_features string from raw_detection JSONB field.
                           Example: "appdisplayname=Zoom=4.21, travel_speed_kmph=1843.50=9.87"
            anomaly_score: DFP mean absolute z-score (float).

        Returns:
            ClassificationResult with sub_category, root_cause, confidence, reasoning.

        Raises:
            RuntimeError: Model not loaded (call .load() first).
        """
        if not self.is_trained:
            raise RuntimeError(
                "Model not loaded. Call clf.load('data/models/root_cause') first, "
                "or run training.py to train the model."
            )

        feature_text = self._build_feature_text(top_features, anomaly_score)
        logits = self._run_inference([feature_text])  # (1, num_labels)

        probs = torch.softmax(logits, dim=-1)[0]  # (num_labels,)
        top_idx = int(torch.argmax(probs).item())
        confidence = float(probs[top_idx].item())
        sub_category = self._idx_to_label[top_idx]
        root_cause = ROOT_CAUSE_MAP.get(sub_category, "Unknown")

        raw_scores = {self._idx_to_label[i]: round(float(p.item()), 4) for i, p in enumerate(probs)}

        reasoning = self._build_reasoning(
            top_features=top_features,
            anomaly_score=anomaly_score,
            sub_category=sub_category,
            root_cause=root_cause,
            confidence=confidence,
            raw_scores=raw_scores,
        )

        return ClassificationResult(
            anomaly_id=anomaly_id,
            sub_category=sub_category,
            root_cause=root_cause,
            confidence=confidence,
            reasoning=reasoning,
            raw_scores=raw_scores,
            feature_text=feature_text,
        )

    def predict_batch(
        self,
        records: list[dict[str, Any]],
        batch_size: int = 32,
    ) -> list[ClassificationResult]:
        """
        Classify a batch of TRUE anomaly records.

        Args:
            records:    List of dicts, each with keys:
                            anomaly_id    (str)
                            top_features  (str)
                            anomaly_score (float)
            batch_size: Number of records to tokenise and forward in one pass.
                        Reduce if OOM on GPU.

        Returns:
            List of ClassificationResult in the same order as the input.

        Raises:
            RuntimeError: Model not loaded.
        """
        if not self.is_trained:
            raise RuntimeError("Model not loaded. Call clf.load() first.")

        results: list[ClassificationResult] = []
        total = len(records)

        for batch_start in range(0, total, batch_size):
            batch = records[batch_start : batch_start + batch_size]
            feature_texts = [
                self._build_feature_text(r.get("top_features", ""), float(r.get("anomaly_score", 0))) for r in batch
            ]

            logits = self._run_inference(feature_texts)  # (batch, num_labels)
            probs = torch.softmax(logits, dim=-1)  # (batch, num_labels)

            for i, record in enumerate(batch):
                p = probs[i]
                top_idx = int(torch.argmax(p).item())
                confidence = float(p[top_idx].item())
                sub_category = self._idx_to_label[top_idx]
                root_cause = ROOT_CAUSE_MAP.get(sub_category, "Unknown")

                raw_scores = {self._idx_to_label[j]: round(float(p[j].item()), 4) for j in range(NUM_LABELS)}
                reasoning = self._build_reasoning(
                    top_features=record.get("top_features", ""),
                    anomaly_score=float(record.get("anomaly_score", 0)),
                    sub_category=sub_category,
                    root_cause=root_cause,
                    confidence=confidence,
                    raw_scores=raw_scores,
                )
                results.append(
                    ClassificationResult(
                        anomaly_id=str(record["anomaly_id"]),
                        sub_category=sub_category,
                        root_cause=root_cause,
                        confidence=confidence,
                        reasoning=reasoning,
                        raw_scores=raw_scores,
                        feature_text=feature_texts[i],
                    )
                )

            logger.debug(f"Classified batch {batch_start}–{batch_start + len(batch) - 1} / {total}")

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_feature_text(top_features: str, anomaly_score: float) -> str:
        """
        Compose the input string for DistilBERT tokenisation.

        Format:
            "features: <top_features> | score: <anomaly_score>"

        The pipe separator creates a natural boundary between the free-form
        feature list and the numeric score, helping the model learn the joint
        signal without conflating the two.  The score is truncated to 2 decimal
        places to reduce tokenisation noise from floating-point representation.

        Examples:
            "features: appdisplayname=Zoom=4.21, travel_speed_kmph=1843.50=9.87 | score: 14.32"
            "features: devicedetailbrowser=Firefox=3.54 | score: 3.54"
            "features:  | score: 2.61"   ← empty top_features is valid
        """
        return f"features: {(top_features or '').strip()} | score: {anomaly_score:.2f}"

    def _run_inference(self, feature_texts: list[str]) -> torch.Tensor:
        """
        Tokenise and forward a list of feature text strings.

        Args:
            feature_texts: Pre-composed strings from _build_feature_text().

        Returns:
            logits: Tensor of shape (len(feature_texts), NUM_LABELS).
        """
        assert self._tokeniser is not None, "Tokeniser not loaded — call .load() first."
        assert self._model is not None, "Model not loaded — call .load() first."

        encoding = self._tokeniser(
            feature_texts,
            padding=True,
            truncation=True,
            max_length=MAX_SEQ_LEN,
            return_tensors="pt",
        )
        input_ids = encoding["input_ids"].to(self.device)
        attention_mask = encoding["attention_mask"].to(self.device)

        with torch.no_grad():
            logits = self._model(input_ids=input_ids, attention_mask=attention_mask)

        return logits  # (batch, NUM_LABELS) — raw logits before softmax

    @staticmethod
    def _build_reasoning(
        top_features: str,
        anomaly_score: float,
        sub_category: str,
        root_cause: str,
        confidence: float,
        raw_scores: dict[str, float],
    ) -> str:
        """
        Build a concise human-readable reasoning string from the prediction.

        This is written to classification_reasoning in enriched_anomalies and
        is visible in the SOC dashboard.  It does NOT call the LLM.

        Example output:
            "DistilBERT classifier (confidence 0.94): Classified as Impossible
             Travel / Geographic Anomaly based on features [travel_speed_kmph,
             locationcountry]. Anomaly score: 14.32."
        """
        # Extract feature names (first part before first '=')
        feat_names: list[str] = []
        for part in (top_features or "").split(","):
            name = part.strip().split("=")[0].strip()
            if name:
                feat_names.append(name)

        feat_str = ", ".join(feat_names[:5]) if feat_names else "N/A"
        if len(feat_names) > 5:
            feat_str += f" (+{len(feat_names) - 5} more)"

        # Top-2 competing classes for transparency
        sorted_scores = sorted(raw_scores.items(), key=lambda x: x[1], reverse=True)
        runner_up = sorted_scores[1] if len(sorted_scores) > 1 else None
        runner_str = f" Runner-up: {runner_up[0]} ({runner_up[1]:.2f})." if runner_up else ""

        return (
            f"DistilBERT classifier (confidence {confidence:.2f}): "
            f"Classified as {sub_category} / {root_cause} "
            f"based on features [{feat_str}]. "
            f"Anomaly score: {anomaly_score:.2f}.{runner_str}"
        )

    @staticmethod
    def _resolve_device(device: str | None) -> str:
        """Auto-detect the best available compute device."""
        if device:
            return device
        if not TORCH_AVAILABLE:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        # Apple Silicon
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"


# ---------------------------------------------------------------------------
# Module-level convenience helpers (used by training.py)
# ---------------------------------------------------------------------------


def build_untrained_classifier(device: str | None = None) -> RootCauseClassifier:
    """
    Return a RootCauseClassifier with a freshly initialised (untrained) model.

    Called by training.py at the start of a new training run.  The caller
    is responsible for setting clf._training_metadata and calling clf.save()
    after training completes.
    """
    if not TORCH_AVAILABLE:
        raise RuntimeError("torch and transformers are required.")

    clf = RootCauseClassifier(device=device)
    clf._model = _build_model().to(clf.device)
    clf._tokeniser = DistilBertTokenizerFast.from_pretrained(DISTILBERT_CHECKPOINT, local_files_only=True)
    logger.info(f"Built untrained RootCauseClassifier on device={clf.device}")
    return clf


def label_to_index(label: str) -> int:
    """Map sub_category string → integer class index (for use in training loss)."""
    try:
        return SUB_CATEGORY_LABELS.index(label)
    except ValueError as e:
        valid = ", ".join(SUB_CATEGORY_LABELS)
        raise ValueError(f"Unknown sub_category '{label}'. Valid values: {valid}") from e


def index_to_label(idx: int) -> str:
    """Map integer class index → sub_category string."""
    if not 0 <= idx < NUM_LABELS:
        raise IndexError(f"Class index {idx} out of range [0, {NUM_LABELS - 1}]")
    return SUB_CATEGORY_LABELS[idx]


# ---------------------------------------------------------------------------
# CLI — quick inference test against the live DB
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import os
    from pathlib import Path

    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).parents[3] / ".env", override=False)
    except ImportError:
        pass

    import psycopg2
    import psycopg2.extras

    parser = argparse.ArgumentParser(description="RootCauseClassifier — inference test against live DB")
    parser.add_argument(
        "--model-dir",
        default=str(DEFAULT_MODEL_DIR),
        help="Path to trained model directory (default: data/models/root_cause)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of TRUE ANOMALY records to classify (default: 10)",
    )
    parser.add_argument(
        "--detection-id",
        help="Classify a specific anomaly_id",
    )
    parser.add_argument(
        "--show-scores",
        action="store_true",
        help="Print raw probability scores for all 9 classes",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Load model
    clf = RootCauseClassifier(model_dir=args.model_dir)
    clf.load()

    # Connect to DB
    from modules.utils.db import get_db_params

    conn = psycopg2.connect(**get_db_params())

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if args.detection_id:
            cur.execute(
                """
                SELECT anomaly_id, anomaly_score,
                       raw_detection->>'top_features' AS top_features,
                       sub_category AS heuristic_sub_category
                FROM enriched_anomalies
                WHERE anomaly_id = %s AND is_anomaly = TRUE
                """,
                (args.detection_id,),
            )
        else:
            cur.execute(
                """
                SELECT anomaly_id, anomaly_score,
                       raw_detection->>'top_features' AS top_features,
                       sub_category AS heuristic_sub_category
                FROM enriched_anomalies
                WHERE is_anomaly = TRUE
                ORDER BY anomaly_score DESC
                LIMIT %s
                """,
                (args.limit,),
            )
        rows = cur.fetchall()

    conn.close()

    print(f"\nClassifying {len(rows)} TRUE ANOMALY record(s)\n{'=' * 70}")

    correct = 0
    for row in rows:
        result = clf.predict(
            anomaly_id=str(row["anomaly_id"]),
            top_features=row["top_features"] or "",
            anomaly_score=float(row["anomaly_score"]),
        )
        match = result.sub_category == (row["heuristic_sub_category"] or "")
        if match:
            correct += 1
        match_str = "✓" if match else "✗"

        print(f"\n{match_str} {result.anomaly_id}")
        print(f"  Predicted : {result.sub_category} / {result.root_cause} ({result.confidence:.2f})")
        print(f"  Heuristic : {row['heuristic_sub_category']}")
        print(f"  Score     : {row['anomaly_score']:.2f}")
        print(f"  Features  : {row['top_features']}")
        if args.show_scores:
            for lbl, p in sorted(result.raw_scores.items(), key=lambda x: x[1], reverse=True):
                bar = "█" * int(p * 30)
                print(f"    {lbl:40s} {p:.3f} {bar}")

    if len(rows) > 1:
        print(f"\n{'=' * 70}")
        print(f"Agreement with heuristic labels: {correct}/{len(rows)} ({100 * correct / len(rows):.1f}%)")
        print("(Disagreement is expected — classifier learns from data, not heuristic rules)\n")
