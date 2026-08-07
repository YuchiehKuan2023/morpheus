"""
Kafka Consumer Module for DFP Streaming Inference

Consumes streaming events from Kafka following NVIDIA Morpheus DFP
ControlMessageKafkaSourceStage pattern.

NVIDIA Reference:
    nv-morpheus/examples/digital_fingerprinting/production/
    dfp_integrated_training_streaming_pipeline.py (lines 69-71)

    Uses confluent-kafka Consumer with JSON message decoding,
    batch consumption, and offset management.

Architecture:
    Kafka Topic → Consumer → JSON Decode → Batch Buffer → Pipeline

Key Features:
    - JSON message decoding
    - Configurable batch consumption
    - Automatic offset management
    - Error handling and reconnection
    - Graceful shutdown support

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-13
"""

import json
import logging
from datetime import datetime
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException

logger = logging.getLogger(__name__)


class DFPKafkaConsumer:
    """
    Kafka consumer for DFP streaming data ingestion.

    Follows NVIDIA Morpheus ControlMessageKafkaSourceStage pattern for
    consuming streaming events from Kafka topics.

    Attributes:
        bootstrap_servers: Kafka broker address (e.g., "localhost:29092")
        topic: Kafka topic to consume from
        group_id: Consumer group ID for offset management
        consumer: confluent-kafka Consumer instance
        running: Flag indicating if consumer is active

    Example:
        ```python
        consumer = DFPKafkaConsumer(
            bootstrap_servers="localhost:29092",
            topic="dfp-events",
            group_id="dfp-inference"
        )

        for messages in consumer.consume_batch(batch_size=100, timeout=1.0):
            process_events(messages)

        consumer.close()
        ```
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        auto_offset_reset: str = "earliest",
        enable_auto_commit: bool = True,
        auto_commit_interval_ms: int = 5000,
        session_timeout_ms: int = 30000,
        max_poll_records: int = 500,
        **kafka_config: Any,
    ):
        """
        Initialize Kafka consumer.

        Args:
            bootstrap_servers: Kafka broker address (host:port)
            topic: Kafka topic name to consume from
            group_id: Consumer group ID for coordinated consumption
            auto_offset_reset: Where to start consuming: "earliest", "latest"
            enable_auto_commit: Automatically commit offsets
            auto_commit_interval_ms: Auto-commit interval in milliseconds
            session_timeout_ms: Session timeout for consumer group
            max_poll_records: Maximum records per poll
            **kafka_config: Additional Kafka configuration parameters
        """
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.group_id = group_id
        self.running = False

        # Build Kafka consumer configuration (NVIDIA pattern)
        consumer_config = {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": enable_auto_commit,
            "auto.commit.interval.ms": auto_commit_interval_ms,
            "session.timeout.ms": session_timeout_ms,
            "max.poll.interval.ms": 300000,  # 5 minutes
            **kafka_config,
        }

        try:
            self.consumer = Consumer(consumer_config)
            self.consumer.subscribe([topic])
            self.running = True

            logger.info(
                f"DFPKafkaConsumer initialized: "
                f"bootstrap_servers={bootstrap_servers}, topic={topic}, "
                f"group_id={group_id}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize Kafka consumer: {e}")
            raise

    def consume_batch(self, batch_size: int = 100, timeout: float = 1.0) -> list[dict[str, Any]]:
        """
        Consume a batch of messages from Kafka.

        Polls Kafka topic and accumulates messages up to batch_size
        or until timeout expires. Returns list of decoded JSON messages.

        Args:
            batch_size: Maximum messages to consume in one batch
            timeout: Poll timeout in seconds (NVIDIA default: 1.0)

        Returns:
            List of decoded message dictionaries

        Raises:
            KafkaException: On unrecoverable Kafka errors
        """
        messages = []
        start_time = datetime.now()

        while len(messages) < batch_size and self.running:
            # Poll for message (NVIDIA pattern: 1 second timeout)
            msg = self.consumer.poll(timeout=timeout)

            if msg is None:
                # No message within timeout
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= timeout:
                    break
                continue

            if msg.error():
                # Handle Kafka errors
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # End of partition - not an error
                    logger.debug(
                        f"Reached end of partition: {msg.topic()} [{msg.partition()}] at offset {msg.offset()}"
                    )
                    break
                else:
                    # Real error - log and raise
                    error_msg = f"Kafka error: {msg.error()}"
                    logger.error(error_msg)
                    raise KafkaException(msg.error())

            # Decode message value
            try:
                raw_value = msg.value()
                if raw_value is None:
                    logger.warning("Received null message value, skipping")
                    continue

                # Decode JSON (NVIDIA pattern: UTF-8 encoded JSON)
                decoded = json.loads(raw_value.decode("utf-8"))

                # Add Kafka metadata
                decoded["_kafka_offset"] = msg.offset()
                decoded["_kafka_partition"] = msg.partition()
                decoded["_kafka_timestamp"] = msg.timestamp()[1] if msg.timestamp()[0] > 0 else None

                messages.append(decoded)

            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON message at offset {msg.offset()}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error processing message at offset {msg.offset()}: {e}")
                continue

        if messages:
            logger.debug(f"Consumed {len(messages)} messages from topic '{self.topic}'")

        return messages

    def consume_stream(self, batch_size: int = 100, poll_interval: float = 1.0):
        """
        Generator that continuously consumes messages in batches.

        Yields batches of messages as they arrive from Kafka. Runs
        until consumer is stopped via stop() method.

        Args:
            batch_size: Maximum messages per batch
            poll_interval: Seconds between polls (NVIDIA default: 1.0)

        Yields:
            List[Dict[str, Any]]: Batch of decoded messages

        Example:
            ```python
            for batch in consumer.consume_stream(batch_size=100):
                if batch:
                    process_batch(batch)
            ```
        """
        logger.info(
            f"Starting continuous consumption from topic '{self.topic}' "
            f"(batch_size={batch_size}, poll_interval={poll_interval})"
        )

        while self.running:
            try:
                batch = self.consume_batch(batch_size=batch_size, timeout=poll_interval)
                if batch:
                    yield batch
            except KafkaException as e:
                logger.error(f"Kafka error during stream consumption: {e}")
                # On error, wait briefly before retrying
                import time

                time.sleep(poll_interval)
            except Exception as e:
                logger.error(f"Unexpected error during stream consumption: {e}")
                break

        logger.info("Stream consumption stopped")

    def commit(self, asynchronous: bool = True):
        """
        Manually commit current offsets.

        Args:
            asynchronous: Commit asynchronously (non-blocking)
        """
        try:
            if asynchronous:
                self.consumer.commit(asynchronous=True)
            else:
                self.consumer.commit()
            logger.debug("Offsets committed successfully")
        except Exception as e:
            logger.error(f"Failed to commit offsets: {e}")

    def seek_to_beginning(self):
        """
        Seek to the beginning of all assigned partitions.

        Useful for reprocessing data from the start.
        """
        try:
            partitions = self.consumer.assignment()
            for partition in partitions:
                self.consumer.seek(partition)
            logger.info("Seeked to beginning of all partitions")
        except Exception as e:
            logger.error(f"Failed to seek to beginning: {e}")

    def get_position(self) -> dict[int, int]:
        """
        Get current position (offset) for all assigned partitions.

        Returns:
            Dictionary mapping partition ID to current offset
        """
        positions = {}
        try:
            partitions = self.consumer.assignment()
            for partition in partitions:
                offset = self.consumer.position([partition])[0].offset
                positions[partition.partition] = offset
        except Exception as e:
            logger.error(f"Failed to get consumer position: {e}")

        return positions

    def stop(self):
        """
        Stop consuming messages.

        Sets running flag to False, which will cause consume_stream()
        to terminate gracefully.
        """
        logger.info("Stopping Kafka consumer...")
        self.running = False

    def close(self):
        """
        Close the Kafka consumer and release resources.

        Should be called when consumer is no longer needed to ensure
        graceful shutdown and proper offset commits.
        """
        if not self.running:
            self.stop()

        try:
            # Final commit before closing
            self.consumer.commit()
            self.consumer.close()
            logger.info("Kafka consumer closed successfully")
        except Exception as e:
            logger.error(f"Error closing Kafka consumer: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False


def create_consumer(config: dict[str, Any]) -> DFPKafkaConsumer:
    """
    Factory function to create Kafka consumer from configuration.

    Args:
        config: Configuration dictionary with Kafka settings

    Returns:
        Configured DFPKafkaConsumer instance

    Example:
        ```python
        config = {
            'kafka': {
                'bootstrap_servers': 'localhost:29092',
                'input_topic': 'dfp-events',
                'consumer_group': 'dfp-inference'
            }
        }
        consumer = create_consumer(config)
        ```
    """
    kafka_config = config.get("kafka", {})

    bootstrap_servers = kafka_config.get("bootstrap_servers", "localhost:29092")
    topic = kafka_config.get("input_topic", "dfp-events")
    group_id = kafka_config.get("consumer_group", "dfp-inference")

    return DFPKafkaConsumer(
        bootstrap_servers=bootstrap_servers,
        topic=topic,
        group_id=group_id,
        auto_offset_reset=kafka_config.get("auto_offset_reset", "earliest"),
        enable_auto_commit=kafka_config.get("enable_auto_commit", True),
        auto_commit_interval_ms=kafka_config.get("auto_commit_interval_ms", 5000),
        session_timeout_ms=kafka_config.get("session_timeout_ms", 30000),
    )
