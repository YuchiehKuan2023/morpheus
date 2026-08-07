"""
Kafka Producer Module for DFP Streaming Inference

Publishes detection results to Kafka following NVIDIA Morpheus DFP
output pattern for streaming pipelines.

NVIDIA Reference:
    nv-morpheus streaming pipelines write detection results to
    output topics for downstream consumption.

Architecture:
    Detection Results → JSON Encode → Producer → Kafka Topic

Key Features:
    - Asynchronous message production
    - Delivery confirmation callbacks
    - JSON serialization
    - Flush control for graceful shutdown
    - Error handling and retry logic

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-13
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from confluent_kafka import KafkaError, Producer

logger = logging.getLogger(__name__)


class DFPKafkaProducer:
    """
    Kafka producer for DFP detection results.

    Publishes anomaly detections and inference results to Kafka topics
    for downstream processing and alerting.

    Attributes:
        bootstrap_servers: Kafka broker address
        topic: Kafka topic to publish to
        producer: confluent-kafka Producer instance
        delivery_callback: Callback for delivery confirmations

    Example:
        ```python
        producer = DFPKafkaProducer(
            bootstrap_servers="localhost:29092",
            topic="dfp-detections"
        )

        detection = {
            'user_id': 'user123',
            'timestamp': '2025-11-13T10:30:00',
            'anomaly_score': 4.5,
            'z_score': 3.8
        }

        producer.produce(detection)
        producer.flush()
        producer.close()
        ```
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        acks: str = "1",
        retries: int = 3,
        max_in_flight: int = 5,
        linger_ms: int = 0,
        batch_size: int = 16384,
        compression_type: str = "gzip",
        delivery_callback: Callable | None = None,
        **kafka_config: Any,
    ):
        """
        Initialize Kafka producer.

        Args:
            bootstrap_servers: Kafka broker address (host:port)
            topic: Kafka topic name to produce to
            acks: Acknowledgment level: "0", "1", "all"
            retries: Number of retries on failure
            max_in_flight: Max unacknowledged requests
            linger_ms: Delay before sending batch (0 for immediate)
            batch_size: Batch size in bytes
            compression_type: Compression: "none", "gzip", "snappy", "lz4", "zstd"
            delivery_callback: Callback for delivery confirmations
            **kafka_config: Additional Kafka configuration
        """
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.delivery_callback = delivery_callback or self._default_delivery_callback

        # Build producer configuration
        producer_config = {
            "bootstrap.servers": bootstrap_servers,
            "acks": acks,
            "retries": retries,
            "max.in.flight.requests.per.connection": max_in_flight,
            "linger.ms": linger_ms,
            "batch.size": batch_size,
            "compression.type": compression_type,
            **kafka_config,
        }

        try:
            self.producer = Producer(producer_config)

            logger.info(
                f"DFPKafkaProducer initialized: "
                f"bootstrap_servers={bootstrap_servers}, topic={topic}, "
                f"acks={acks}, compression={compression_type}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            raise

    def _default_delivery_callback(self, err: KafkaError | None, msg: Any):
        """
        Default delivery confirmation callback.

        Args:
            err: KafkaError if delivery failed, None if successful
            msg: Message object with metadata
        """
        if err is not None:
            logger.error(f"Message delivery failed: {err} (topic={msg.topic()}, partition={msg.partition()})")
        else:
            logger.debug(f"Message delivered: topic={msg.topic()}, partition={msg.partition()}, offset={msg.offset()}")

    def produce(
        self,
        value: dict[str, Any],
        key: str | None = None,
        headers: dict[str, str] | None = None,
        timestamp: int | None = None,
    ):
        """
        Produce a single message to Kafka.

        Args:
            value: Message payload (will be JSON-encoded)
            key: Optional message key for partitioning
            headers: Optional message headers
            timestamp: Optional message timestamp (milliseconds since epoch)

        Raises:
            BufferError: If producer queue is full
            KafkaException: On unrecoverable Kafka errors
        """
        # Serialize value to JSON
        serialized_value = json.dumps(value).encode("utf-8")

        # Serialize key if provided
        serialized_key = key.encode("utf-8") if key else None

        # Convert headers to list of tuples if provided
        kafka_headers = None
        if headers:
            kafka_headers = [(k, v.encode("utf-8")) for k, v in headers.items()]

        try:
            # Build produce arguments
            produce_args = {
                "topic": self.topic,
                "value": serialized_value,
                "key": serialized_key,
                "headers": kafka_headers,
                "callback": self.delivery_callback,
            }

            # Only include timestamp if it's not None
            if timestamp is not None:
                produce_args["timestamp"] = timestamp

            # Produce message (asynchronous)
            self.producer.produce(**produce_args)

            # Poll to handle delivery callbacks (non-blocking)
            self.producer.poll(0)

        except BufferError:
            # Queue is full - flush and retry
            logger.warning("Producer queue full, flushing...")
            self.flush()

            # Rebuild produce arguments for retry
            produce_args = {
                "topic": self.topic,
                "value": serialized_value,
                "key": serialized_key,
                "headers": kafka_headers,
                "callback": self.delivery_callback,
            }

            if timestamp is not None:
                produce_args["timestamp"] = timestamp

            # Retry once
            self.producer.produce(**produce_args)
        except Exception as e:
            logger.error(f"Failed to produce message: {e}")
            raise

    def produce_batch(
        self, messages: list[dict[str, Any]], key_field: str | None = None, timestamp_field: str | None = None
    ) -> int:
        """
        Produce a batch of messages to Kafka.

        Args:
            messages: List of message payloads
            key_field: Field name to use as message key (e.g., "user_id")
            timestamp_field: Field name to use as message timestamp

        Returns:
            Number of messages successfully queued

        Example:
            ```python
            detections = [
                {'user_id': 'user1', 'anomaly_score': 4.5},
                {'user_id': 'user2', 'anomaly_score': 3.8}
            ]
            queued = producer.produce_batch(detections, key_field='user_id')
            ```
        """
        queued_count = 0
        for message in messages:
            try:
                # Extract key if specified
                key = None
                if key_field and key_field in message:
                    key = str(message[key_field])

                # Extract timestamp if specified
                timestamp = None
                if timestamp_field and timestamp_field in message:
                    ts_value = message[timestamp_field]
                    if ts_value is not None:  # Only process if not None
                        try:
                            # Convert to milliseconds since epoch
                            if isinstance(ts_value, datetime):
                                timestamp = int(ts_value.timestamp() * 1000)
                            elif isinstance(ts_value, str):
                                dt = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
                                timestamp = int(dt.timestamp() * 1000)
                            elif isinstance(ts_value, (int, float)):
                                timestamp = int(ts_value)
                        except Exception as e:
                            logger.warning(f"Failed to parse timestamp '{ts_value}': {e}")

                # If timestamp is still None, don't pass timestamp parameter
                # (Kafka will use current server time)

                self.produce(value=message, key=key, timestamp=timestamp)
                queued_count += 1

            except Exception as e:
                logger.error(f"Failed to produce message in batch: {e}")
                continue

        logger.debug(f"Produced batch of {queued_count}/{len(messages)} messages")
        return queued_count

    def flush(self, timeout: float = 10.0) -> int:
        """
        Flush all buffered messages.

        Blocks until all messages are delivered or timeout expires.
        Should be called before shutting down producer to ensure
        all messages are sent.

        Args:
            timeout: Maximum time to wait for flush (seconds)

        Returns:
            Number of messages still in queue after timeout
        """
        try:
            remaining = self.producer.flush(timeout=timeout)

            if remaining > 0:
                logger.warning(f"Flush timeout: {remaining} messages still in queue")
            else:
                logger.debug("All messages flushed successfully")

            return remaining

        except Exception as e:
            logger.error(f"Error during flush: {e}")
            return -1

    def get_queue_size(self) -> int:
        """
        Get number of messages currently in producer queue.

        Returns:
            Number of messages waiting to be sent
        """
        try:
            return len(self.producer)
        except Exception:
            return -1

    def close(self, timeout: float = 10.0):
        """
        Close the producer and release resources.

        Flushes all buffered messages before closing.

        Args:
            timeout: Maximum time to wait for flush (seconds)
        """
        logger.info("Closing Kafka producer...")

        try:
            # Flush remaining messages
            remaining = self.flush(timeout=timeout)

            if remaining > 0:
                logger.warning(f"Producer closed with {remaining} messages undelivered")

            logger.info("Kafka producer closed successfully")

        except Exception as e:
            logger.error(f"Error closing Kafka producer: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False


def create_producer(config: dict[str, Any]) -> DFPKafkaProducer:
    """
    Factory function to create Kafka producer from configuration.

    Args:
        config: Configuration dictionary with Kafka settings

    Returns:
        Configured DFPKafkaProducer instance

    Example:
        ```python
        config = {
            'kafka': {
                'bootstrap_servers': 'localhost:29092',
                'output_topic': 'dfp-detections',
                'acks': 'all',
                'compression_type': 'gzip'
            }
        }
        producer = create_producer(config)
        ```
    """
    kafka_config = config.get("kafka", {})

    bootstrap_servers = kafka_config.get("bootstrap_servers", "localhost:29092")
    topic = kafka_config.get("output_topic", "dfp-detections")

    return DFPKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        topic=topic,
        acks=kafka_config.get("acks", "1"),
        retries=kafka_config.get("retries", 3),
        max_in_flight=kafka_config.get("max_in_flight", 5),
        linger_ms=kafka_config.get("linger_ms", 0),
        batch_size=kafka_config.get("batch_size", 16384),
        compression_type=kafka_config.get("compression_type", "gzip"),
    )
