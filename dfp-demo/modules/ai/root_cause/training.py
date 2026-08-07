#!/usr/bin/env python3
"""
Root Cause Classifier — Stage 2 Training Script

Fine-tunes a DistilBERT classification head on enriched_anomalies records
that carry LLM- or heuristic-assigned sub_category labels.

Training data query
-------------------
    SELECT anomaly_id,
           raw_detection->>'top_features'  AS top_features,
           anomaly_score,
           sub_category,
           validation_confidence
    FROM   enriched_anomalies
    WHERE  is_anomaly = TRUE
      AND  sub_category IS NOT NULL
    ORDER  BY validation_confidence DESC

Training signal quality
-----------------------
    - validation_confidence ≥ 0.80 : LLM-validated or high-confidence
      heuristic label → treated as ground truth.
    - 0.60 ≤ validation_confidence < 0.80 : midband heuristic label →
      down-weighted in the loss to reduce noise without throwing away data.
    - Records with unknown sub_category strings (outside SUB_CATEGORY_LABELS)
      are skipped with a warning — they represent early LLM hallucinations.

Loss formulation
----------------
    Per-sample confidence-weighted cross-entropy:

        L = -Σ_i  w_i · log p(y_i | x_i)  /  Σ_i w_i

    where w_i = validation_confidence_i.  This is equivalent to hard labels
    with importance weighting: highly-confirmed labels dominate learning.

Architecture
------------
    DistilBERT CLS → Linear(768→768) + ReLU + Dropout(0.3) → Linear(768→9)
    Full fine-tuning (all DistilBERT layers + head) — not frozen pretrained.

    With only ~350 samples we deliberately keep learning rates small (2e-5)
    and add a high dropout (0.3) to prevent overfitting on the small dataset.
    As LLM batch_labeler supplies more confirmed labels over time, subsequent
    retraining runs will naturally benefit from more data.

MLflow experiment
-----------------
    Experiment name: "root_cause_classifier"
    Logged per run:  params (lr, epochs, batch_size …)
                     metrics per epoch (train_loss, val_loss, val_accuracy,
                                        val_f1_macro, val_f1_weighted)
                     artifact: config.json from saved model directory

Usage
-----
    # Most common: defaults for everything
    python -m modules.ai.root_cause.training

    # Custom hyperparameters
    python -m modules.ai.root_cause.training --epochs 10 --lr 1e-5 --batch-size 16

    # Dry run — report dataset statistics, do not train
    python -m modules.ai.root_cause.training --dry-run

    # Force CPU even when Apple Silicon MPS is available
    python -m modules.ai.root_cause.training --device cpu

Reference
---------
    docs/implementation/PROGRESS_TRACKER.md  (Week 11-14: Stage 2 Training)
    modules/ai/root_cause/classifier.py       (model architecture + save/load)
    modules/ai/root_cause/labeling_worker.py  (periodic inference using saved model)

Author: AI Intelligence Layer Team
Date: 2026-03-03
"""

from __future__ import annotations

import logging
import os
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

# ---------------------------------------------------------------------------
# Optional heavy dependencies — same lazy-import pattern as classifier.py
# ---------------------------------------------------------------------------
if TYPE_CHECKING:
    import mlflow
    import mlflow.pytorch
    import torch
    import torch.nn as nn
    from sklearn.metrics import classification_report, f1_score
    from sklearn.model_selection import train_test_split
    from torch.utils.data import DataLoader, Dataset

try:
    import torch  # type: ignore[no-redef]
    import torch.nn as nn  # type: ignore[no-redef]
    from torch.utils.data import DataLoader, Dataset  # type: ignore[no-redef]

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    import mlflow  # type: ignore[no-redef]
    import mlflow.pytorch  # type: ignore[no-redef]

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False

try:
    from sklearn.metrics import classification_report, f1_score  # type: ignore[no-redef]
    from sklearn.model_selection import train_test_split  # type: ignore[no-redef]

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Sibling-module imports
# ---------------------------------------------------------------------------
# Allow running as `python modules/ai/root_cause/training.py` from project root
sys.path.append(str(Path(__file__).parents[3]))

from modules.ai.root_cause.classifier import (  # noqa: E402
    MAX_SEQ_LEN,
    NUM_LABELS,
    SUB_CATEGORY_LABELS,
    build_untrained_classifier,
    label_to_index,
)
from modules.utils.db import get_db_params  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB connection defaults (override with env vars)
# ---------------------------------------------------------------------------
DB_CONFIG: dict[str, Any] = get_db_params()

# ---------------------------------------------------------------------------
# Hyperparameter defaults
# ---------------------------------------------------------------------------
DEFAULT_EPOCHS = 5
DEFAULT_BATCH_SIZE = 16
DEFAULT_LR = 2e-5
DEFAULT_WEIGHT_DECAY = 0.01
DEFAULT_PATIENCE = 3  # early stopping: stop after this many non-improving epochs
DEFAULT_MIN_CONFIDENCE = 0.0  # filter: skip records below this confidence threshold
DEFAULT_MIN_SAMPLES = 20  # abort training if fewer than this many valid samples
MLFLOW_EXPERIMENT = "root_cause_classifier"


# ---------------------------------------------------------------------------
# Training record (raw from DB, before tokenisation)
# ---------------------------------------------------------------------------


@dataclass
class TrainingRecord:
    anomaly_id: str
    top_features: str
    anomaly_score: float
    sub_category: str
    validation_confidence: float
    label_idx: int  # derived by label_to_index(sub_category)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class AnomalyDataset(Dataset):  # type: ignore[type-arg]
    """
    PyTorch Dataset wrapping a list of TrainingRecord.

    Each item is a dict with:
        input_ids       (LongTensor, seq_len)
        attention_mask  (LongTensor, seq_len)
        label           (LongTensor, scalar)
        weight          (FloatTensor, scalar) = validation_confidence

    Tokenisation uses DistilBertTokenizerFast from the shared classifier
    tokeniser to guarantee the exact same vocabulary and truncation as inference.
    """

    def __init__(
        self,
        records: list[TrainingRecord],
        tokeniser: Any,
        max_length: int = MAX_SEQ_LEN,
    ):
        self._records = records
        self._tokeniser = tokeniser
        self._max_length = max_length

        # Pre-compose all feature strings so __getitem__ does only indexing
        self._feature_texts: list[str] = [
            f"features: {r.top_features.strip()} | score: {r.anomaly_score:.2f}" for r in records
        ]

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        record = self._records[idx]
        encoding = self._tokeniser(
            self._feature_texts[idx],
            padding="max_length",
            truncation=True,
            max_length=self._max_length,
            return_tensors="pt",
        )
        return {
            "input_ids": encoding["input_ids"].squeeze(0),  # (seq_len,)
            "attention_mask": encoding["attention_mask"].squeeze(0),  # (seq_len,)
            "label": torch.tensor(record.label_idx, dtype=torch.long),
            "weight": torch.tensor(record.validation_confidence, dtype=torch.float),
        }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_training_data(
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[TrainingRecord]:
    """
    Query enriched_anomalies for labelled TRUE anomalies.

    Skips records whose sub_category is not in SUB_CATEGORY_LABELS
    (guards against early LLM hallucinations that pre-date the closed taxonomy).

    Args:
        min_confidence: Skip records with validation_confidence < this value.

    Returns:
        List of TrainingRecord, sorted descending by validation_confidence.
    """
    query = """
        SELECT
            anomaly_id::text,
            COALESCE(raw_detection->>'top_features', '')  AS top_features,
            anomaly_score,
            sub_category,
            COALESCE(validation_confidence, 0.5)         AS validation_confidence
        FROM  enriched_anomalies
        WHERE is_anomaly = TRUE
          AND sub_category IS NOT NULL
          AND sub_category <> ''
        ORDER BY validation_confidence DESC
    """

    logger.info("Connecting to DB to load training data…")
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            rows = cur.fetchall()
    finally:
        conn.close()

    records: list[TrainingRecord] = []
    skipped_unknown = 0
    skipped_confidence = 0

    for row in rows:
        sub_cat: str = row["sub_category"]
        conf: float = float(row["validation_confidence"])

        if conf < min_confidence:
            skipped_confidence += 1
            continue

        try:
            idx = label_to_index(sub_cat)
        except ValueError:
            logger.warning(f"Unknown sub_category '{sub_cat}' for anomaly_id={row['anomaly_id']} — skipped.")
            skipped_unknown += 1
            continue

        records.append(
            TrainingRecord(
                anomaly_id=row["anomaly_id"],
                top_features=row["top_features"] or "",
                anomaly_score=float(row["anomaly_score"]),
                sub_category=sub_cat,
                validation_confidence=conf,
                label_idx=idx,
            )
        )

    logger.info(
        f"Loaded {len(records)} records "
        f"(skipped {skipped_unknown} unknown labels, "
        f"{skipped_confidence} below min_confidence={min_confidence:.2f})"
    )
    return records


# ---------------------------------------------------------------------------
# Stratified train / val split
# ---------------------------------------------------------------------------


def split_records(
    records: list[TrainingRecord],
    val_fraction: float = 0.20,
    random_seed: int = 42,
) -> tuple[list[TrainingRecord], list[TrainingRecord]]:
    """
    80/20 stratified split on sub_category label.

    Falls back to random split if any class has fewer than 2 samples
    (necessary for stratification).

    Returns:
        (train_records, val_records)
    """
    if not SKLEARN_AVAILABLE:
        raise RuntimeError("scikit-learn is required. Install with: pip install scikit-learn")

    labels = [r.label_idx for r in records]

    # Check class counts — stratify needs ≥2 per class
    from collections import Counter

    counts = Counter(labels)
    single_count_classes = [SUB_CATEGORY_LABELS[idx] for idx, cnt in counts.items() if cnt < 2]

    if single_count_classes:
        warnings.warn(
            f"Classes with only 1 sample (cannot stratify): {single_count_classes}. "
            "Using random split instead. Collect more data for these categories.",
            stacklevel=2,
        )
        stratify = None
    else:
        stratify = labels

    train_recs, val_recs = train_test_split(
        records,
        test_size=val_fraction,
        stratify=stratify,
        random_state=random_seed,
    )
    return list(train_recs), list(val_recs)


# ---------------------------------------------------------------------------
# Loss helper — confidence-weighted cross-entropy
# ---------------------------------------------------------------------------


def weighted_cross_entropy(
    logits: torch.Tensor,  # (batch, num_labels)
    labels: torch.Tensor,  # (batch,) dtype=long
    weights: torch.Tensor,  # (batch,) dtype=float — validation_confidence
) -> torch.Tensor:
    """
    Confidence-weighted cross-entropy loss.

    L = -Σ_i  w_i  · log p(y_i | x_i)  /  Σ_i w_i

    Args:
        logits:  Raw model outputs before softmax.
        labels:  Integer class indices.
        weights: Per-sample importance weights (validation_confidence).

    Returns:
        Scalar loss tensor.
    """
    ce_loss = nn.functional.cross_entropy(logits, labels, reduction="none")  # (batch,)
    weighted = ce_loss * weights
    return weighted.sum() / weights.sum()


# ---------------------------------------------------------------------------
# Epoch training step
# ---------------------------------------------------------------------------


def _train_epoch(
    model: nn.Module,
    loader: DataLoader,  # type: ignore[type-arg]
    optimizer: torch.optim.Optimizer,  # type: ignore[attr-defined]
    device: str,
) -> float:
    """Run one training epoch.  Returns mean weighted loss."""
    model.train()
    total_loss = 0.0
    n_batches = 0

    for batch in loader:
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        labels = batch["label"].to(device)
        weights = batch["weight"].to(device)

        optimizer.zero_grad()
        logits = model(input_ids=input_ids, attention_mask=attention_mask)
        loss = weighted_cross_entropy(logits, labels, weights)
        loss.backward()
        optimizer.step()

        total_loss += loss.item()
        n_batches += 1

    return total_loss / max(n_batches, 1)


# ---------------------------------------------------------------------------
# Epoch validation step
# ---------------------------------------------------------------------------


@dataclass
class ValMetrics:
    loss: float
    accuracy: float
    f1_macro: float
    f1_weighted: float
    report: str = field(default="", repr=False)


def _val_epoch(
    model: nn.Module,
    loader: DataLoader,  # type: ignore[type-arg]
    device: str,
) -> ValMetrics:
    """Run one validation pass.  Returns metrics dataclass."""
    model.eval()
    total_loss = 0.0
    n_batches = 0
    all_labels: list[int] = []
    all_preds: list[int] = []

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["label"].to(device)
            weights = batch["weight"].to(device)

            logits = model(input_ids=input_ids, attention_mask=attention_mask)
            loss = weighted_cross_entropy(logits, labels, weights)
            total_loss += loss.item()
            n_batches += 1

            preds = torch.argmax(logits, dim=-1).cpu().tolist()
            all_preds.extend(preds)
            all_labels.extend(labels.cpu().tolist())

    val_loss = total_loss / max(n_batches, 1)
    accuracy = sum(p == t for p, t in zip(all_preds, all_labels, strict=True)) / max(len(all_labels), 1)

    f1_macro = float(
        f1_score(all_labels, all_preds, average="macro", zero_division=0)  # type: ignore[call-arg]
        if SKLEARN_AVAILABLE
        else 0.0
    )
    f1_weighted = float(
        f1_score(all_labels, all_preds, average="weighted", zero_division=0)  # type: ignore[call-arg]
        if SKLEARN_AVAILABLE
        else 0.0
    )
    report: str = (
        str(
            classification_report(
                all_labels,
                all_preds,
                target_names=SUB_CATEGORY_LABELS,
                zero_division=0,
            )
        )
        if SKLEARN_AVAILABLE
        else ""
    )

    return ValMetrics(
        loss=val_loss,
        accuracy=accuracy,
        f1_macro=f1_macro,
        f1_weighted=f1_weighted,
        report=report,
    )


# ---------------------------------------------------------------------------
# Print dataset statistics
# ---------------------------------------------------------------------------


def print_dataset_stats(records: list[TrainingRecord]) -> None:
    """Print a per-class breakdown of the training corpus."""
    from collections import Counter

    counts = Counter(r.sub_category for r in records)
    total = len(records)
    avg_conf = sum(r.validation_confidence for r in records) / max(total, 1)
    max_label_len = max(len(s) for s in SUB_CATEGORY_LABELS)

    print(f"\nDataset statistics ({total} labelled TRUE anomalies, avg confidence={avg_conf:.3f})")
    print(f"{'Sub-category':{max_label_len}}  {'n':>5}  {'%':>6}  {'avg_conf':>8}")
    print("-" * (max_label_len + 25))

    for lbl in SUB_CATEGORY_LABELS:
        n = counts.get(lbl, 0)
        lbl_avg_conf = sum(r.validation_confidence for r in records if r.sub_category == lbl) / n if n > 0 else 0.0
        pct = 100 * n / total if total else 0.0
        miss = "  ← NO SAMPLES" if n == 0 else ""
        print(f"{lbl:{max_label_len}}  {n:>5}  {pct:>5.1f}%  {lbl_avg_conf:>8.3f}{miss}")

    print()


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------


def train(
    epochs: int = DEFAULT_EPOCHS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lr: float = DEFAULT_LR,
    weight_decay: float = DEFAULT_WEIGHT_DECAY,
    patience: int = DEFAULT_PATIENCE,
    model_dir: str | Path = "data/models/root_cause",
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    device: str | None = None,
    mlflow_tracking_uri: str | None = None,
    dry_run: bool = False,
    no_mlflow: bool = False,
) -> dict[str, Any]:
    """
    Full training run: load data → split → fine-tune → validate → save.

    Args:
        epochs:               Maximum training epochs.
        batch_size:           Samples per gradient update.
        lr:                   AdamW learning rate.
        weight_decay:         AdamW weight decay for regularisation.
        patience:             Early stopping patience (epochs without val_acc improvement).
        model_dir:            Where to save the trained classifier.
        min_confidence:       Skip training records below this confidence.
        min_samples:          Abort if fewer than this many valid training records exist.
        device:               "cpu" | "cuda" | "mps" | None (auto-detect).
        mlflow_tracking_uri:  MLflow server URI (None → use MLFLOW_TRACKING_URI env var
                              or local ./mlruns directory).
        dry_run:              Print statistics and exit without training.

    Returns:
        dict containing best_val_accuracy, best_val_f1_macro, epochs_trained,
        model_dir, and the final classification_report string.
    """
    if not TORCH_AVAILABLE:
        raise RuntimeError("torch and transformers are required. Install with: pip install torch transformers")

    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    records = load_training_data(min_confidence=min_confidence)

    if dry_run:
        print_dataset_stats(records)
        return {"dry_run": True, "n_samples": len(records)}

    if len(records) < min_samples:
        raise RuntimeError(
            f"Only {len(records)} labelled records found (minimum {min_samples}). "
            "Run batch_labeler.py to generate more training labels before training."
        )

    print_dataset_stats(records)

    # ------------------------------------------------------------------
    # 2. Train / val split
    # ------------------------------------------------------------------
    train_records, val_records = split_records(records)
    logger.info(f"Split: {len(train_records)} train / {len(val_records)} val")

    # ------------------------------------------------------------------
    # 3. Build classifier (fresh weights)
    # ------------------------------------------------------------------
    clf = build_untrained_classifier(device=device)
    assert clf._model is not None, "build_untrained_classifier() must set _model"
    assert clf._tokeniser is not None, "build_untrained_classifier() must set _tokeniser"
    model_device = clf.device

    # ------------------------------------------------------------------
    # 4. Datasets & DataLoaders
    # ------------------------------------------------------------------
    train_dataset = AnomalyDataset(train_records, clf._tokeniser)
    val_dataset = AnomalyDataset(val_records, clf._tokeniser)

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=0,  # keep simple; data fits in RAM
        pin_memory=(model_device != "cpu"),
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size * 2,  # no gradients → larger batch is fine
        shuffle=False,
        num_workers=0,
        pin_memory=(model_device != "cpu"),
    )

    # ------------------------------------------------------------------
    # 5. Optimizer and LR scheduler
    # ------------------------------------------------------------------
    optimizer = torch.optim.AdamW(  # type: ignore[attr-defined]
        clf._model.parameters(),
        lr=lr,
        weight_decay=weight_decay,
    )
    # Linear warm-up for 10 % of total steps, then linear decay to 0
    total_steps = epochs * len(train_loader)
    warmup_steps = max(1, total_steps // 10)
    scheduler = torch.optim.lr_scheduler.LinearLR(
        optimizer,
        start_factor=0.1,
        end_factor=1.0,
        total_iters=warmup_steps,
    )

    # ------------------------------------------------------------------
    # 6. MLflow setup
    # ------------------------------------------------------------------
    run_id: str | None = None
    _mlflow_active = MLFLOW_AVAILABLE and not no_mlflow
    if _mlflow_active:
        _local_mlruns = str(Path(__file__).parents[3] / "mlruns")
        if mlflow_tracking_uri:
            mlflow.set_tracking_uri(mlflow_tracking_uri)
        elif os.getenv("MLFLOW_TRACKING_URI"):
            pass  # use whatever the environment specifies
        else:
            mlflow.set_tracking_uri(_local_mlruns)

        try:
            mlflow.set_experiment(MLFLOW_EXPERIMENT)
            logger.info(f"MLflow tracking URI: {mlflow.get_tracking_uri()}")
        except Exception as exc:
            logger.warning(
                f"MLflow server unreachable ({mlflow.get_tracking_uri()}): {exc}. Falling back to local file store."
            )
            mlflow.set_tracking_uri(_local_mlruns)
            try:
                mlflow.set_experiment(MLFLOW_EXPERIMENT)
                logger.info(f"MLflow tracking via local file store: {_local_mlruns}")
            except Exception as exc2:
                logger.warning(f"MLflow local fallback also failed ({exc2}); disabling tracking.")
                _mlflow_active = False
    elif not MLFLOW_AVAILABLE:
        logger.warning("mlflow not installed — metrics will not be tracked. Install with: pip install mlflow")

    # ------------------------------------------------------------------
    # 7. Training loop
    # ------------------------------------------------------------------
    run_start = datetime.now(tz=timezone.utc)
    best_val_accuracy = 0.0
    best_val_f1_macro = 0.0
    best_epoch = 0
    best_report = ""
    no_improve_count = 0
    history: list[dict[str, float]] = []
    epoch = 0  # initialised here so it is always bound after the loop

    hparams = {
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "weight_decay": weight_decay,
        "patience": patience,
        "min_confidence": min_confidence,
        "device": model_device,
        "distilbert_checkpoint": "distilbert-base-uncased",
        "max_seq_len": MAX_SEQ_LEN,
        "n_train": len(train_records),
        "n_val": len(val_records),
        "n_labels": NUM_LABELS,
    }

    mlflow_ctx = (
        mlflow.start_run(run_name=f"distilbert_{run_start.strftime('%Y%m%d_%H%M%S')}")
        if _mlflow_active
        else _NullContext()
    )

    with mlflow_ctx as active_run:
        if _mlflow_active and active_run is not None:
            run_id = active_run.info.run_id
            mlflow.log_params(hparams)

        print("\nTraining DistilBERT root cause classifier")
        print(f"  Device : {model_device}")
        print(f"  Train  : {len(train_records)} samples")
        print(f"  Val    : {len(val_records)} samples")
        print(f"  Epochs : up to {epochs} (patience={patience})")
        print(f"  LR     : {lr}\n")

        # Define warm-up duration in epoch units to match epoch-based scheduler stepping
        warmup_epochs = max(1, int(0.1 * epochs))

        for epoch in range(1, epochs + 1):
            train_loss = _train_epoch(clf._model, train_loader, optimizer, model_device)

            # Only step scheduler during warm-up phase (measured in epochs)
            if epoch <= warmup_epochs:
                scheduler.step()

            val_metrics = _val_epoch(clf._model, val_loader, model_device)

            epoch_row = {
                "epoch": epoch,
                "train_loss": train_loss,
                "val_loss": val_metrics.loss,
                "val_accuracy": val_metrics.accuracy,
                "val_f1_macro": val_metrics.f1_macro,
                "val_f1_weighted": val_metrics.f1_weighted,
            }
            history.append(epoch_row)

            if _mlflow_active:
                mlflow.log_metrics(
                    {
                        "train_loss": train_loss,
                        "val_loss": val_metrics.loss,
                        "val_accuracy": val_metrics.accuracy,
                        "val_f1_macro": val_metrics.f1_macro,
                        "val_f1_weighted": val_metrics.f1_weighted,
                    },
                    step=epoch,
                )

            print(
                f"Epoch {epoch:>3}/{epochs}  "
                f"train_loss={train_loss:.4f}  "
                f"val_loss={val_metrics.loss:.4f}  "
                f"val_acc={val_metrics.accuracy:.4f}  "
                f"val_f1={val_metrics.f1_macro:.4f}"
            )

            # Early stopping check
            if val_metrics.accuracy > best_val_accuracy:
                best_val_accuracy = val_metrics.accuracy
                best_val_f1_macro = val_metrics.f1_macro
                best_epoch = epoch
                best_report = val_metrics.report
                no_improve_count = 0
            else:
                no_improve_count += 1
                logger.debug(f"No improvement for {no_improve_count}/{patience} epoch(s)")

            if no_improve_count >= patience:
                print(f"\nEarly stopping at epoch {epoch} (no val_accuracy improvement for {patience} epochs).")
                break

        # ------------------------------------------------------------------
        # 8. Save model
        # ------------------------------------------------------------------
        clf._training_metadata = {
            "trained_at": run_start.isoformat(),
            "best_epoch": best_epoch,
            "epochs_trained": epoch,
            "best_val_accuracy": round(best_val_accuracy, 4),
            "best_val_f1_macro": round(best_val_f1_macro, 4),
            "n_train": len(train_records),
            "n_val": len(val_records),
            "hyperparameters": hparams,
            "mlflow_run_id": run_id,
        }

        saved_dir = clf.save(model_dir)
        logger.info(f"Model saved to {saved_dir}")

        if _mlflow_active:
            mlflow.log_metrics(
                {
                    "best_val_accuracy": best_val_accuracy,
                    "best_val_f1_macro": best_val_f1_macro,
                    "best_epoch": float(best_epoch),
                }
            )
            config_path = saved_dir / "config.json"
            if config_path.exists():
                mlflow.log_artifact(str(config_path))

    # ------------------------------------------------------------------
    # 9. Final report
    # ------------------------------------------------------------------
    print(f"\n{'=' * 70}")
    print(f"Training complete (best epoch {best_epoch})")
    print(f"  Best val accuracy  : {best_val_accuracy:.4f}")
    print(f"  Best val F1-macro  : {best_val_f1_macro:.4f}")
    print(f"  Model saved to     : {saved_dir}")
    if run_id:
        print(f"  MLflow run ID      : {run_id}")
    print()

    if best_report:
        print("Per-class classification report (best epoch):")
        print(best_report)

    return {
        "best_val_accuracy": best_val_accuracy,
        "best_val_f1_macro": best_val_f1_macro,
        "epochs_trained": epoch,
        "best_epoch": best_epoch,
        "model_dir": str(saved_dir),
        "classification_report": best_report,
        "mlflow_run_id": run_id,
    }


# ---------------------------------------------------------------------------
# Helper: null context manager for when MLflow is not available
# ---------------------------------------------------------------------------


class _NullContext:
    """Drop-in for mlflow.start_run() when mlflow is not installed."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).parents[3] / ".env", override=False)
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Train the DistilBERT root cause classifier on enriched_anomalies data",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS, help="Maximum training epochs")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Training batch size")
    parser.add_argument("--lr", type=float, default=DEFAULT_LR, help="AdamW learning rate")
    parser.add_argument("--weight-decay", type=float, default=DEFAULT_WEIGHT_DECAY, help="AdamW weight decay")
    parser.add_argument("--patience", type=int, default=DEFAULT_PATIENCE, help="Early stopping patience (epochs)")
    parser.add_argument(
        "--model-dir",
        default="data/models/root_cause",
        help="Directory to save the trained model",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=DEFAULT_MIN_CONFIDENCE,
        help="Minimum validation_confidence to include a training record",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_SAMPLES,
        help="Abort if fewer than this many valid training samples are found",
    )
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], help="Force a specific compute device")
    parser.add_argument("--mlflow-tracking-uri", help="MLflow tracking server URI")
    parser.add_argument(
        "--no-mlflow",
        action="store_true",
        help="Skip MLflow tracking entirely (useful when the MLflow server is not running)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print dataset statistics and exit without training",
    )
    args = parser.parse_args()

    result = train(
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        patience=args.patience,
        model_dir=args.model_dir,
        min_confidence=args.min_confidence,
        min_samples=args.min_samples,
        device=args.device,
        mlflow_tracking_uri=args.mlflow_tracking_uri,
        dry_run=args.dry_run,
        no_mlflow=args.no_mlflow,
    )

    if not args.dry_run:
        sys.exit(0 if result.get("best_val_accuracy", 0) > 0 else 1)
