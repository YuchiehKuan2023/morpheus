"""
DFP Inference Pipeline - NVIDIA Morpheus Modular Real-Time Streaming Pattern

Implements NVIDIA's dfp_inference_pipe module pattern for real-time streaming inference
with DFP behavioral learning and FilterDetections binary filtering.
Reference: python/morpheus_dfp/morpheus_dfp/modules/dfp_inference_pipe.py

Architecture (NVIDIA Modular Real-Time Streaming):
    Kafka Stream (single events, poll_interval="10millis")
        ↓
    DFP_PREPROC (file_to_df → split_users)
        ↓
    dfp_rolling_window (cache_mode="batch", 1d history WITH geographic features, reads last_train_count)
        ↓
    dfp_data_prep (calculates geographic + increment features using baseline)
        ↓ [Features include travel_speed_kmph for behavioral learning]
    dfp_inference (loads model, predicts behavioral + geographic z-scores)
        ↓
    filter_detections (NVIDIA standard binary filtering, mean_abs_z > 2.0)
        ↓
    Kafka Output Topic (dfp-detections)

DFP Behavioral Learning:
    - AutoEncoder trained on behavioral + geographic features (including travel_speed_kmph)
    - Models learn normal patterns per user (typically 0-100 km/h for travel)
    - FilterDetections provides post-inference binary filtering (threshold configurable)

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-12-01
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from modules.control.control_message import ControlMessage
from modules.inference.dfp_inference import DFPInference
from modules.inference.filter_detections import FilterDetections
from modules.io.kafka_consumer import DFPKafkaConsumer
from modules.io.kafka_producer import DFPKafkaProducer
from modules.preprocessing.column_info import process_dataframe
from modules.preprocessing.data_prep import DataPrep
from modules.preprocessing.dfp_preprocessing import DFPPreprocessing
from modules.preprocessing.rolling_window import RollingWindow
from modules.preprocessing.source_schema import build_azure_source_schema
from modules.preprocessing.user_splitting import UserSplitter
from modules.utils.metrics_utils import PipelineMetrics
from modules.utils.score_utils import compress_score
from scripts.utils import extract_event_timestamp

logger = logging.getLogger(__name__)


class DFPInferencePipeline:
    """
    NVIDIA Morpheus DFP Inference Pipeline (Modular Real-Time Streaming).

    Follows NVIDIA's dfp_inference_pipe module pattern with DFP behavioral learning:
    - Kafka Source: poll_interval="10millis" (NVIDIA default)
    - DFP_PREPROC: file_to_df → split_users
    - dfp_rolling_window: batch mode (1d history WITH geographic features, reads last_train_count)
    - dfp_data_prep: applies preprocess_schema (geographic + increment features)
    - dfp_inference: loads models from MLflow, predicts behavioral + geographic z-scores
    - filter_detections: NVIDIA standard binary filtering (mean_abs_z > 2.0, configurable)
    - kafka_producer: publishes filtered detections to Kafka

    DFP Behavioral Learning:
        - AutoEncoder trained on behavioral + geographic features (including travel_speed_kmph)
        - Models learn normal travel patterns per user (typically 0-100 km/h)
        - Z-score based anomaly detection across all features
        - FilterDetections provides post-inference binary filtering

    CRITICAL: Uses batch cache mode (preserves last_train_count from training, per-event reload).

    Reference:
        /nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_inference_pipe.py
    """

    def __init__(self, config: dict[str, Any], cache_dir: str, mlflow_manager: Any, metrics: PipelineMetrics):
        """
        Initialize inference pipeline.

        Args:
            config: Pipeline configuration
            cache_dir: Cache directory for rolling window (shared with training)
            mlflow_manager: MLflow manager instance
            metrics: Pipeline metrics collector
        """
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.mlflow_manager = mlflow_manager
        self.metrics = metrics

        # Initialize alert manager
        from modules.utils.alerting_utils import get_alert_manager

        self.alert_manager = get_alert_manager()

        # Initialize detection output file (directory created by mkdir if needed)
        self.output_dir = Path("data/output/detections")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.detections_file = self.output_dir / f"detections_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.detections_written = False

        # Initialize modules
        self._init_modules()

        logger.info("DFP Inference Pipeline initialized (NVIDIA modular real-time streaming)")

    def _init_modules(self):
        """Initialize inference pipeline modules."""

        # DFP_PREPROC: user_splitter
        self.user_splitter = UserSplitter(
            userid_column=self.config.get("userid_column", "username"),
            include_generic=False,
            include_individual=True,
            timestamp_column=self.config.get("timestamp_column", "timestamp"),
        )

        # dfp_rolling_window (NVIDIA Module API - batch mode for continuous streaming)
        # Note: RollingWindow adds "rolling-user-data" subdirectory internally
        # CRITICAL: cache_to_disk=True to persist total_count accumulation between events
        inference_config = self.config.get("inference", {})
        self.rolling_window = RollingWindow(
            cache_dir=str(self.cache_dir),
            timestamp_column=self.config.get("timestamp_column", "timestamp"),
            cache_mode="batch",  # Batch mode for continuous streaming
            cache_to_disk=True,  # Saves BEFORE get_spanning_df() - preserves last_train_count
            min_history=inference_config.get("min_history", 1),
            min_increment=inference_config.get("min_increment", 0),
            max_history=inference_config.get("max_history", "1d"),
        )

        # dfp_data_prep (applies preprocess_schema)
        self.preprocessing = DFPPreprocessing(
            {
                "schema_file": self.config.get("schema_file", "config/feature_schema.yaml"),
                "feature_set": self.config.get("feature_set", "default"),
                "fill_missing": True,
                "preserve_columns": [
                    "_batch_id",
                    "location_geoCoordinates_latitude",
                    "location_geoCoordinates_longitude",
                ],
            }
        )

        # Data preparation (feature selection)
        self.data_prep = DataPrep(
            {
                "feature_columns": list(self.config.get("feature_columns", [])),
                "timestamp_column": self.config.get("timestamp_column", "timestamp"),
                "userid_column": self.config.get("userid_column", "username"),
                "exclude_columns": [],
            }
        )

        # dfp_inference (loads models from MLflow)
        self.inference_module = DFPInference(
            {
                "mlflow": {
                    "tracking_uri": self.mlflow_manager.tracking_uri,
                    "model_name_formatter": self.config.get("mlflow", {}).get("model_name_formatter", "DFP-{user_id}"),
                },
                "inference": {
                    "fallback_username": "generic_user",
                    "model_fetch_timeout": self.config.get("inference", {}).get("model_fetch_timeout", 1.0),
                    "timestamp_column_name": self.config.get("timestamp_column", "timestamp"),
                },
            }
        )

        # FilterDetections stage (NVIDIA standard binary filtering)
        self.filter_detections = FilterDetections(
            {
                "detection_criteria": {
                    "field_name": "mean_abs_z",
                    "threshold": self.config.get("anomaly_threshold", {}).get("value", 2.0),
                    "filter_source": "DATAFRAME",
                },
                "output": {"copy_data": True},
            }
        )
        logger.info(
            f"FilterDetections initialized (threshold: {self.config.get('anomaly_threshold', {}).get('value', 2.0)})"
        )

        # Source schema for Kafka events
        self.source_schema = build_azure_source_schema()

    def run(
        self,
        kafka_bootstrap: str = "127.0.0.1:29092",
        input_topic: str = "dfp-events",
        output_topic: str = "dfp-detections",
        clean_topic: str = "dfp-clean-events",
        group_id: str = "morpheus-dfp-inference",
        poll_interval: str = "10millis",
    ):
        """
        Execute real-time streaming inference following NVIDIA modular pattern.

        NVIDIA dfp_inference_pipe flow (streaming):
            1. Kafka Source: poll_interval="10millis" (NVIDIA default)
            2. DFP_PREPROC: split_users (per-event processing)
            3. dfp_rolling_window: batch mode (per-event with disk reload, includes geographic features)
            4. dfp_data_prep: preprocess_schema (geographic + increment features using baseline)
            5. dfp_inference: load model → predict behavioral + geographic z-scores
            6. filter_detections: NVIDIA standard binary filtering (mean_abs_z > 2.0)
            7. kafka_producer: publish filtered detections to Kafka

        DFP Behavioral Learning:
            - AutoEncoder trained on behavioral + geographic features (including travel_speed_kmph)
            - Models learn normal patterns per user (typically 0-100 km/h for travel)
            - Z-score based anomaly detection across all features
            - FilterDetections provides post-inference binary filtering

        Args:
            kafka_bootstrap: Kafka broker address
            input_topic: Topic to consume events from
            output_topic: Topic to publish detections to
            group_id: Kafka consumer group ID
            poll_interval: Polling interval (NVIDIA default: "10millis")
        """
        logger.info("=" * 80)
        logger.info("DFP INFERENCE PIPELINE (NVIDIA Modular Real-Time Streaming)")
        logger.info("=" * 80)
        logger.info(f"Kafka bootstrap: {kafka_bootstrap}")
        logger.info(f"Input topic: {input_topic}")
        logger.info(f"Output topic: {output_topic}")
        logger.info(f"Clean topic: {clean_topic}")
        logger.info(f"Poll interval: {poll_interval} (NVIDIA default)")
        logger.info("Cache mode: batch (per-event processing, preserves last_train_count)")
        logger.info(f"Max history: {self.rolling_window.max_history}")

        # Initialize Kafka consumer/producer
        kafka_consumer = DFPKafkaConsumer(
            bootstrap_servers=kafka_bootstrap,
            topic=input_topic,
            group_id=group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            auto_commit_interval_ms=5000,
        )

        kafka_producer = DFPKafkaProducer(
            bootstrap_servers=kafka_bootstrap, topic=output_topic, acks="1", compression_type="gzip"
        )

        # Producer for non-anomaly events → AI orchestrator training data bookkeeping
        kafka_producer_clean = DFPKafkaProducer(
            bootstrap_servers=kafka_bootstrap, topic=clean_topic, acks="1", compression_type="gzip"
        )

        # Counters
        event_count = 0
        detection_count = 0
        batch_count = 0
        start_time = datetime.now(timezone.utc)

        # Start alert manager
        self.alert_manager.start(interval=30)
        logger.info("Alert manager started (30s evaluation interval)")

        logger.info("\nStarting real-time event stream...")
        logger.info("Press Ctrl+C to stop\n")

        try:
            # Parse poll interval
            poll_seconds = pd.Timedelta(poll_interval).total_seconds()

            # Stream events (NVIDIA pattern: batched consumption)
            for event_batch in kafka_consumer.consume_stream(batch_size=100, poll_interval=poll_seconds):
                if not event_batch:
                    continue

                logger.debug(f"Processing batch of {len(event_batch)} events")
                batch_count += 1
                event_count += len(event_batch)

                # Record metrics
                self.metrics.record_batch_processed(count=1)
                self.metrics.record_events_processed(count=len(event_batch))

                try:
                    # Index raw Kafka events by user identity BEFORE any processing
                    # so we can include the original nested event structure in detections
                    # If multiple events for the same user appear in a batch, keep only
                    # the event with the latest timestamp so that the stored "original"
                    # event deterministically matches the event being processed.
                    raw_events_by_user: dict[str, dict] = {}
                    for _raw_ev in event_batch:
                        _uid = _raw_ev.get("identity") or _raw_ev.get("properties", {}).get("userPrincipalName", "")
                        if not _uid:
                            continue

                        existing_event = raw_events_by_user.get(_uid)
                        if existing_event is None:
                            raw_events_by_user[_uid] = _raw_ev
                            continue

                        # Retain the event with the latest timestamp so original_event
                        # matches the last-scored row (windowed_df.iloc[-1]).
                        new_ts = extract_event_timestamp(_raw_ev)
                        if new_ts is None:
                            continue

                        existing_ts = extract_event_timestamp(existing_event)
                        if existing_ts is None or new_ts >= existing_ts:
                            raw_events_by_user[_uid] = _raw_ev

                    # Module 1: Create DataFrame from batch
                    batch_df = pd.DataFrame(event_batch)

                    # Module 2: DFP_PREPROC - apply source_schema (simple transforms)
                    if self.source_schema:
                        batch_df = process_dataframe(batch_df, self.source_schema)

                    # Module 3: DFP_PREPROC - split_users
                    user_dfs = self.user_splitter.split_users(batch_df)

                    # NOTE: Geographic feature calculation happens AFTER rolling window
                    # in DFPPreprocessing.preprocess() where we have full user history.
                    # Calculating here would fail because each Kafka batch has only 1 event,
                    # but calculate_travel_features() requires 2+ events to compute distances.

                    # Process each user
                    for user_id, user_df in user_dfs.items():
                        try:
                            # Module 4: dfp_rolling_window (batch mode, per-event processing WITH geographic features)
                            windowed_df = self.rolling_window.build_window(user_id=user_id, incoming_df=user_df)

                            if windowed_df is None or len(windowed_df) == 0:
                                logger.debug(f"No window for {user_id} (insufficient history)")
                                continue

                            # Module 5: dfp_data_prep (calculates increment features)
                            preprocessed_df = self.preprocessing.preprocess(windowed_df)

                            features = self.data_prep.prepare(preprocessed_df)

                            if features is None or len(features) == 0:
                                continue

                            # Module 6: dfp_inference
                            inference_msg = ControlMessage()
                            inference_msg.set_metadata("user_id", user_id)
                            inference_msg.add_task("inference", {})
                            inference_msg.payload(features)

                            result_msg = self.inference_module.infer(inference_msg)

                            if result_msg is None:
                                continue

                            detections = result_msg.payload()
                            if detections is None or len(detections) == 0:
                                continue

                            # CRITICAL NVIDIA DFP PATTERN:
                            # - Rolling window returns historical context (e.g., 1 day = many rows)
                            # - Inference scores ALL rows (model needs context)
                            # - BUT we only filter the LAST row (the NEW event just added)
                            # - This prevents re-detecting old anomalies from history
                            #
                            # Example: Kenneth has 26 rows in his 1-day window
                            # - 25 old rows (already processed)
                            # - 1 new row (just added)
                            # - Extract ONLY the new row for filtering

                            # Extract timestamp from the original windowed data (before preprocessing removed it)
                            timestamp_col = self.config.get("timestamp_column", "timestamp")
                            event_timestamp = None
                            if windowed_df is not None and len(windowed_df) > 0:
                                # Get timestamp from the last row (the new event)
                                for ts_col in [timestamp_col, "time", "timestamp", "datetime", "event_time"]:
                                    if ts_col in windowed_df.columns:
                                        event_timestamp = windowed_df.iloc[-1][ts_col]
                                        if event_timestamp is not None and event_timestamp != "":
                                            break

                            last_row_df = detections.iloc[[-1]].copy()  # Single row DataFrame
                            # Create message with only the new event
                            last_row_msg = ControlMessage()
                            last_row_msg.set_metadata("user_id", user_id)
                            last_row_msg.payload(last_row_df)

                            # Module 7: filter_detections (NVIDIA standard binary filtering)
                            filtered_msg = self.filter_detections.filter(last_row_msg)

                            if filtered_msg is None:
                                # No anomalies detected (NVIDIA standard: return None)
                                logger.debug(f"No anomalies for user_id='{user_id}'")
                                # Forward the raw event to the AI orchestrator for
                                # training data bookkeeping (clean-event path)
                                raw_event: dict[str, Any] = raw_events_by_user.get(user_id, {})
                                if not raw_event:
                                    logger.warning(
                                        f"No raw event found for user_id='{user_id}' — skipping clean-event publish"
                                    )
                                    continue
                                # Inject the DFP score so the AI orchestrator can
                                # store it in user_training_events.anomaly_score and
                                # surface it on the simulation card for proximity-to-
                                # threshold visibility.  The score is available from
                                # last_row_df even though it was below threshold.
                                try:
                                    raw_event["_dfp_score"] = float(last_row_df.iloc[0]["mean_abs_z"])
                                except (KeyError, IndexError, TypeError, ValueError):
                                    pass  # non-critical — omit the field if unavailable
                                kafka_producer_clean.produce(value=raw_event, key=user_id)
                                continue

                            # Extract filtered anomalies (only rows above threshold)
                            filtered_detections = filtered_msg.payload()

                            # Type guard: ensure filtered_detections is not None
                            if filtered_detections is None or len(filtered_detections) == 0:
                                logger.debug(f"Empty filtered detections for user_id='{user_id}'")
                                continue

                            num_detections = len(filtered_detections)
                            detection_count += num_detections

                            # Record metrics (after filtering)
                            self.metrics.record_anomalies_detected(count=num_detections)
                            detection_rate = (detection_count / event_count * 100) if event_count > 0 else 0
                            self.metrics.record_detection_rate(rate=detection_rate)

                            # Process all filtered detections
                            timestamp_col = self.config.get("timestamp_column", "timestamp")
                            threshold = self.config.get("anomaly_threshold", {}).get("value", 2.0)

                            for _idx, row in filtered_detections.iterrows():
                                anomaly_score = float(row["mean_abs_z"])
                                max_score = float(row.get("max_abs_z", anomaly_score))

                                # Use the preserved timestamp from original event (extracted before preprocessing)
                                timestamp = event_timestamp

                                # Convert timestamp to ISO format string
                                if timestamp is not None and timestamp != "":
                                    if hasattr(timestamp, "isoformat"):
                                        timestamp = timestamp.isoformat()
                                    else:
                                        timestamp = str(timestamp)
                                else:
                                    timestamp = ""

                                anomaly_source = row.get("anomaly_source", "dfp")

                                # Find ALL contributing features (z-score columns)
                                z_cols = [col for col in row.index if col.endswith("_z_loss")]
                                feature_details = []
                                top_features_simple = []

                                if z_cols:
                                    feature_data = []
                                    for col in z_cols:
                                        feature_name = col.replace("_z_loss", "")
                                        z_score = abs(float(row[col]))

                                        # Get the actual feature value from original data
                                        feature_value = row.get(feature_name, "N/A")
                                        if feature_value is not None:
                                            # Convert to appropriate type
                                            if hasattr(feature_value, "item"):  # numpy types
                                                feature_value = feature_value.item()
                                            elif isinstance(feature_value, (int | float | str | bool)):
                                                feature_value = feature_value
                                            else:
                                                feature_value = str(feature_value)

                                        feature_data.append(
                                            {
                                                "feature": feature_name,
                                                "z_score": compress_score(z_score),
                                                "value": feature_value,
                                            }
                                        )

                                    # Sort by z-score (descending)
                                    feature_data.sort(key=lambda x: x["z_score"], reverse=True)
                                    feature_details = feature_data

                                    # Keep simple format for backward compatibility (top 3)
                                    # Show actual values (not z-scores) in top_features for human readability
                                    top_features_simple = [
                                        (f["feature"], f["value"], f["z_score"]) for f in feature_data[:3]
                                    ]

                                # Record z-score metric
                                self.metrics.record_z_score(z_score=anomaly_score)

                                # Compress all z-score-derived values via the shared utility so
                                # that anomaly_score, max_abs_z, and individual feature z_scores
                                # are all on the same scale and remain mutually consistent for
                                # LLM reasoning (no more contradictory astronomical feature scores
                                # alongside a bounded aggregate score).
                                # Monotonicity is fully preserved: compress(max_abs_z) ≥
                                # compress(anomaly_score) because max_abs_z ≥ mean_abs_z.
                                # See modules/utils/score_utils.py for the formula and reference table.
                                stored_score = compress_score(anomaly_score)
                                stored_max_z = compress_score(max_score)

                                detection_record = {
                                    "user_id": user_id,
                                    "timestamp": timestamp,
                                    "anomaly_score": stored_score,
                                    "max_abs_z": stored_max_z,
                                    "threshold": threshold,
                                    "anomaly_source": anomaly_source,
                                    "event_count": num_detections,
                                    "feature_count": len(feature_details),
                                    "features": feature_details,
                                    "top_features": ", ".join(
                                        [f"{feat}={val} (z={z:.2f})" for feat, val, z in top_features_simple]
                                    ),
                                    # Raw Azure AD event — used by AI orchestrator for enrichment context
                                    "original_event": raw_events_by_user.get(user_id, {}),
                                }

                                # Write to CSV (simplified version without nested features array)
                                write_header = not self.detections_written
                                csv_record = {
                                    "user_id": user_id,
                                    "timestamp": timestamp,
                                    "anomaly_score": detection_record["anomaly_score"],
                                    "max_abs_z": detection_record[
                                        "max_abs_z"
                                    ],  # compressed, same scale as anomaly_score
                                    "threshold": threshold,
                                    "anomaly_source": anomaly_source,
                                    "event_count": num_detections,
                                    "feature_count": len(feature_details),
                                    "top_features": detection_record["top_features"],
                                }
                                with open(self.detections_file, "a", newline="") as f:
                                    writer = csv.DictWriter(f, fieldnames=csv_record.keys())
                                    if write_header:
                                        writer.writeheader()
                                        self.detections_written = True
                                    writer.writerow(csv_record)

                                # Publish to Kafka (full comprehensive record with features array)
                                kafka_producer.produce(value=detection_record, key=user_id)

                                # Enhanced logging with complete feature breakdown
                                logger.warning(
                                    f"ANOMALY DETECTED: {user_id}\n"
                                    f"  Timestamp: {timestamp}\n"
                                    f"  Mean z-score: {anomaly_score:.2f} → stored {stored_score:.4f} (threshold: {threshold})\n"
                                    f"  Max z-score: {max_score:.2f} → stored {stored_max_z:.4f}\n"
                                    f"  Source: {anomaly_source}\n"
                                    f"  Feature count: {len(feature_details)}\n"
                                    f"  Top contributing features:"
                                )
                                # Show top 10 features in logs (not all to keep logs manageable)
                                for feature_info in feature_details[:10]:
                                    logger.warning(
                                        f"    - {feature_info['feature']}: "
                                        f"z={feature_info['z_score']:.2f}, "
                                        f"value={feature_info['value']}"
                                    )
                                if len(feature_details) > 10:
                                    logger.warning(f"    ... and {len(feature_details) - 10} more features")

                                logger.warning(f"  {'=' * 60}")

                            kafka_producer.flush()

                        except Exception as e:
                            logger.error(f"Error processing user {user_id}: {e}")
                            self.metrics.record_errors(count=1)
                            continue

                except Exception as e:
                    logger.error(f"Error processing batch: {e}")
                    self.metrics.record_errors(count=1)
                    continue

                # Log progress and record metrics every 100 events
                if event_count > 0 and event_count % 100 == 0:
                    detection_rate = (detection_count / event_count * 100) if event_count > 0 else 0
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    throughput = event_count / elapsed if elapsed > 0 else 0

                    # Record metrics
                    self.metrics.record_throughput(events_per_second=throughput)

                    logger.info(
                        f"Progress: {event_count} events | "
                        f"{detection_count} anomalies ({detection_rate:.1f}%) | "
                        f"throughput: {throughput:.1f} events/sec"
                    )

        except KeyboardInterrupt:
            logger.info("\nStreaming stopped by user (Ctrl+C)")

        finally:
            # Cleanup
            logger.info("Shutting down inference pipeline...")

            # Stop alert manager
            self.alert_manager.stop()
            logger.info("Alert manager stopped")

            # Close Kafka connections
            kafka_consumer.close()
            kafka_producer.close()
            kafka_producer_clean.close()

            # Calculate final metrics
            detection_rate = (detection_count / event_count * 100) if event_count > 0 else 0
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            throughput = event_count / elapsed if elapsed > 0 else 0

            # Record final metrics
            self.metrics.record_detection_rate(rate=detection_rate)
            self.metrics.record_throughput(events_per_second=throughput)

            # Log metrics summary
            self.metrics.log_summary()

            logger.info("\n" + "=" * 80)
            logger.info("INFERENCE COMPLETE")
            logger.info(f"  Total batches: {batch_count:,}")
            logger.info(f"  Total events: {event_count:,}")
            logger.info(f"  Total anomalies: {detection_count:,}")
            logger.info(f"  Detection rate: {detection_rate:.1f}%")
            logger.info(f"  Throughput: {throughput:.1f} events/sec")
            logger.info(f"  Duration: {elapsed:.1f} seconds")
            if self.detections_written:
                logger.info(f"  Detections saved to: {self.detections_file}")
            logger.info("=" * 80)
