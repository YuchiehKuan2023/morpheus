"""
NVIDIA Morpheus DFP Pipeline - 100% Modular Compliant

Main pipeline orchestrator following NVIDIA's modular pattern exactly.
Uses separate training_pipeline.py and inference_pipeline.py modules.

Architecture:
    - Training: dfp_training_pipe (aggregate mode, 60d history)
    - Inference: dfp_inference_pipe (aggregate mode, 1d history, real-time streaming)

Reference:
    - /nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_training_pipe.py
    - /nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_inference_pipe.py

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-21
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, cast

# Add modules to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.utils.config_utils import ConfigLoader
from modules.utils.logging_utils import setup_logging
from modules.utils.metrics_utils import PipelineMetrics, SystemMetrics
from modules.utils.mlflow_utils import MLflowManager
from pipelines.inference_pipeline import DFPInferencePipeline
from pipelines.training_pipeline import DFPTrainingPipeline

logger = logging.getLogger(__name__)


class DFPPipeline:
    """
    NVIDIA Morpheus DFP Pipeline - 100% Modular Compliant.

    Orchestrates training and inference pipelines following NVIDIA's
    modular architecture exactly:

    Training Pipeline (dfp_training_pipe):
        - DFP_PREPROC → dfp_rolling_window → dfp_data_prep →
          dfp_training → mlflow_model_writer
        - cache_mode="aggregate" (60d history, preserves last_train_count)

    Inference Pipeline (dfp_inference_pipe):
        - Kafka Source → DFP_PREPROC → dfp_rolling_window → dfp_data_prep →
          dfp_inference → dfp_postprocessing → Kafka Sink
        - cache_mode="aggregate" (1d history, reads last_train_count)
        - poll_interval="10millis" (NVIDIA default for real-time)

    Reference:
        /nv-morpheus/examples/digital_fingerprinting/production/
    """

    def __init__(
        self,
        config_path: str,
        cache_dir: str = ".cache/demo",
        mlflow_uri: str = "http://localhost:5001",
        log_level: str = "INFO",
    ):
        """
        Initialize DFP pipeline.

        Args:
            config_path: Path to pipeline configuration YAML
            cache_dir: Cache directory for rolling window (shared between training/inference)
            mlflow_uri: MLflow tracking server URI
            log_level: Logging level
        """
        print("Initializing NVIDIA Morpheus DFP Pipeline (100% Modular)...", flush=True)
        setup_logging(log_level)

        logger.info("=" * 80)
        logger.info("NVIDIA MORPHEUS DFP - MODULAR PIPELINE")
        logger.info("=" * 80)
        logger.info(f"Configuration: {config_path}")

        # Resolve cache_dir relative to project root
        project_root = Path(__file__).parent.parent.parent
        if not cache_dir.startswith("/"):
            cache_dir = str(project_root / cache_dir)

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Cache directory: {cache_dir}")
        logger.info(f"MLflow URI: {mlflow_uri}")

        # Load configuration
        config_loader = ConfigLoader(Path(config_path).parent)
        loaded_config = config_loader.load(Path(config_path).stem)

        # Convert DictConfig to plain dict for pipeline modules
        from omegaconf import OmegaConf

        config_dict = OmegaConf.to_container(loaded_config, resolve=True)

        # Type assertion for static analysis
        if not isinstance(config_dict, dict):
            raise ValueError("Configuration must be a dictionary")
        self.config = cast(dict[str, Any], config_dict)

        # Initialize MLflow
        self.mlflow_manager = MLflowManager(mlflow_uri)

        # Initialize monitoring
        self.metrics = PipelineMetrics(pipeline_name="dfp_modular")
        self.system_metrics = SystemMetrics()

        # Start metrics HTTP server (in-process, background thread)
        from modules.utils.metrics_utils import start_metrics_server

        logger.info("Starting metrics HTTP server (port 8000)...")
        self.metrics_server = start_metrics_server(port=8000)
        if self.metrics_server:
            logger.info("Metrics server running at http://localhost:8000/metrics")
        else:
            logger.warning("Metrics server failed to start (port may be in use)")

        # Initialize pipelines
        logger.info("\nInitializing pipeline modules...")
        self.training_pipeline = DFPTrainingPipeline(
            config=self.config, cache_dir=str(self.cache_dir), mlflow_manager=self.mlflow_manager, metrics=self.metrics
        )

        self.inference_pipeline = DFPInferencePipeline(
            config=self.config, cache_dir=str(self.cache_dir), mlflow_manager=self.mlflow_manager, metrics=self.metrics
        )

        logger.info("Pipeline initialized (NVIDIA modular pattern)")
        logger.info("   - Training: dfp_training_pipe (aggregate mode)")
        logger.info("   - Inference: dfp_inference_pipe (aggregate mode, real-time)")

    def load_control_message(self, message_path: str) -> dict[str, Any]:
        """Load control message from JSON file."""
        logger.info(f"Loading control message: {message_path}")
        with open(message_path) as f:
            message = json.load(f)

        if "tasks" not in message or not message["tasks"]:
            raise ValueError(f"Invalid control message: {message_path}")

        return message

    def run_training(self, train_message_path: str) -> dict[str, Any]:
        """
        Run training pipeline.

        Executes NVIDIA's dfp_training_pipe modular pattern:
            DFP_PREPROC → dfp_rolling_window → dfp_data_prep →
            dfp_training → mlflow_model_writer

        Args:
            train_message_path: Path to training control message

        Returns:
            Training statistics
        """
        logger.info("=" * 80)
        logger.info("STARTING TRAINING")
        logger.info("=" * 80)

        try:
            # Load control message
            train_message = self.load_control_message(train_message_path)
            data_path = train_message["tasks"][0]["properties"]["data_path"]

            # Execute training pipeline
            stats = self.training_pipeline.run(data_path)

            # Log metrics summary
            self.metrics.log_summary()

            return {"success": True, "training": stats}

        except Exception as e:
            logger.error(f"Training failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def run_inference(
        self,
        kafka_bootstrap: str = "127.0.0.1:29092",
        input_topic: str = "dfp-events",
        output_topic: str = "dfp-detections",
        group_id: str = "morpheus-dfp-inference",
        poll_interval: str = "10millis",
    ):
        """
        Run inference pipeline in real-time streaming mode.

        Executes NVIDIA's dfp_inference_pipe modular pattern:
            Kafka Source → DFP_PREPROC → dfp_rolling_window → dfp_data_prep →
            dfp_inference → dfp_postprocessing → Kafka Sink

        Args:
            kafka_bootstrap: Kafka broker address
            input_topic: Input topic for events
            output_topic: Output topic for detections
            group_id: Consumer group ID
            poll_interval: Polling interval (NVIDIA default: "10millis")
        """
        logger.info("=" * 80)
        logger.info("STARTING INFERENCE (Real-Time Streaming)")
        logger.info("=" * 80)

        try:
            # Execute inference pipeline
            self.inference_pipeline.run(
                kafka_bootstrap=kafka_bootstrap,
                input_topic=input_topic,
                output_topic=output_topic,
                group_id=group_id,
                poll_interval=poll_interval,
            )

        except Exception as e:
            logger.error(f"Inference failed: {e}", exc_info=True)
            raise


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="NVIDIA Morpheus DFP - 100% Modular Compliant Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # TRAINING: Run dfp_training_pipe
    python pipelines/pipeline.py train \\
        --config config/pipeline.yaml \\
        --train-msg control_messages/train.json

    # INFERENCE: Run dfp_inference_pipe (real-time streaming)
    python pipelines/pipeline.py inference \\
        --config config/pipeline.yaml \\
        --kafka-bootstrap 127.0.0.1:29092

Reference:
    NVIDIA Morpheus DFP Modular Pipelines:
    - dfp_training_pipe.py
    - dfp_inference_pipe.py
        """,
    )

    parser.add_argument(
        "mode", type=str, choices=["training", "inference"], help="Pipeline mode: 'training' or 'inference'"
    )

    parser.add_argument("--config", type=str, required=True, help="Path to pipeline configuration YAML")

    # Training arguments
    parser.add_argument("--train-msg", type=str, help="[training] Path to training control message JSON")

    # Inference arguments
    parser.add_argument(
        "--kafka-bootstrap", type=str, default="127.0.0.1:29092", help="[inference] Kafka bootstrap servers"
    )

    parser.add_argument("--input-topic", type=str, default="dfp-events", help="[inference] Kafka input topic")

    parser.add_argument("--output-topic", type=str, default="dfp-detections", help="[inference] Kafka output topic")

    parser.add_argument(
        "--consumer-group", type=str, default="morpheus-dfp-inference", help="[inference] Kafka consumer group ID"
    )

    parser.add_argument(
        "--poll-interval",
        type=str,
        default="10millis",
        help="[inference] Kafka poll interval (NVIDIA default: 10millis)",
    )

    # Common arguments
    parser.add_argument(
        "--cache-dir", type=str, default=".cache/demo", help="Cache directory (shared between training/inference)"
    )

    parser.add_argument("--mlflow-uri", type=str, default="http://localhost:5001", help="MLflow tracking server URI")

    parser.add_argument(
        "--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level"
    )

    args = parser.parse_args()

    # Validate arguments
    if args.mode == "training" and not args.train_msg:
        print("ERROR: Training mode requires --train-msg")
        sys.exit(1)

    if args.mode == "training" and not Path(args.train_msg).exists():
        print(f"ERROR: Training message not found: {args.train_msg}")
        sys.exit(1)

    if not Path(args.config).exists():
        print(f"ERROR: Configuration file not found: {args.config}")
        sys.exit(1)

    # Initialize pipeline
    pipeline = DFPPipeline(
        config_path=args.config, cache_dir=args.cache_dir, mlflow_uri=args.mlflow_uri, log_level=args.log_level
    )

    # Run in appropriate mode
    if args.mode == "training":
        results = pipeline.run_training(args.train_msg)
        sys.exit(0 if results.get("success") else 1)

    elif args.mode == "inference":
        pipeline.run_inference(
            kafka_bootstrap=args.kafka_bootstrap,
            input_topic=args.input_topic,
            output_topic=args.output_topic,
            group_id=args.consumer_group,
            poll_interval=args.poll_interval,
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
