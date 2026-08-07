"""
Alerting utilities for DFP PoC.

This module provides alerting functionality for monitoring critical
pipeline conditions and sending notifications via multiple channels.

Features:
    - Alert rule evaluation
    - Multiple notification channels (log, email, Slack, PagerDuty)
    - Alert inhibition and routing
    - Alert history tracking
"""

import logging
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import yaml

from modules.utils.metrics_utils import get_metrics_collector

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Represents an active alert."""

    name: str
    description: str
    severity: AlertSeverity
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    starts_at: datetime = field(default_factory=datetime.now)
    ends_at: datetime | None = None
    value: float | None = None

    @property
    def is_firing(self) -> bool:
        """Check if alert is still firing."""
        return self.ends_at is None

    @property
    def duration(self) -> timedelta:
        """Get alert duration."""
        end = self.ends_at or datetime.now()
        return end - self.starts_at


class AlertChannel:
    """Base class for alert notification channels."""

    def send(self, alert: Alert):
        """Send alert notification."""
        raise NotImplementedError


class LogAlertChannel(AlertChannel):
    """Log alerts to logging system."""

    def __init__(self, level: str = "ERROR"):
        """Initialize log channel."""
        self.logger = logging.getLogger("dfp.alerts")
        self.level = level.upper()

    def send(self, alert: Alert):
        """Log alert."""
        message = f"[{alert.severity.value.upper()}] {alert.name}: {alert.description}"
        if alert.value is not None:
            message += f" (value: {alert.value})"

        log_func = getattr(self.logger, self.level.lower(), self.logger.error)
        log_func(message)


class FileAlertChannel(AlertChannel):
    """Write alerts to file."""

    def __init__(self, filepath: str):
        """Initialize file channel."""
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def send(self, alert: Alert):
        """Write alert to file."""
        with open(self.filepath, "a") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"{timestamp} - [{alert.severity.value.upper()}] {alert.name}: {alert.description}\n")
            if alert.value is not None:
                f.write(f"  Value: {alert.value}\n")
            for key, value in alert.labels.items():
                f.write(f"  {key}: {value}\n")
            f.write("\n")


class EmailAlertChannel(AlertChannel):
    """Send alerts via email."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_address: str,
        to_addresses: list[str],
    ):
        """Initialize email channel."""
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.to_addresses = to_addresses

    def send(self, alert: Alert):
        """Send alert via email."""
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[{alert.severity.value.upper()}] {alert.name}"
            msg["From"] = self.from_address
            msg["To"] = ", ".join(self.to_addresses)

            # Create body
            body = f"""
Alert: {alert.name}
Severity: {alert.severity.value.upper()}
Description: {alert.description}

Started: {alert.starts_at.isoformat()}
Duration: {alert.duration}

"""
            if alert.value is not None:
                body += f"Value: {alert.value}\n\n"

            if alert.labels:
                body += "Labels:\n"
                for key, value in alert.labels.items():
                    body += f"  {key}: {value}\n"
                body += "\n"

            if alert.annotations:
                body += "Annotations:\n"
                for key, value in alert.annotations.items():
                    body += f"  {key}: {value}\n"

            msg.attach(MIMEText(body, "plain"))

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.debug(f"Alert email sent: {alert.name}")

        except Exception as e:
            logger.error(f"Failed to send alert email: {e}")


class SlackAlertChannel(AlertChannel):
    """Send alerts to Slack."""

    def __init__(self, webhook_url: str, channel: str):
        """Initialize Slack channel."""
        self.webhook_url = webhook_url
        self.channel = channel

    def send(self, alert: Alert):
        """Send alert to Slack."""
        try:
            import requests

            # Create message
            severity_emoji = {
                AlertSeverity.INFO: ":information_source:",
                AlertSeverity.WARNING: ":warning:",
                AlertSeverity.CRITICAL: ":rotating_light:",
            }

            message = {
                "channel": self.channel,
                "attachments": [
                    {
                        "color": self._get_color(alert.severity),
                        "title": f"{severity_emoji.get(alert.severity, '')} {alert.name}",
                        "text": alert.description,
                        "fields": [
                            {"title": "Severity", "value": alert.severity.value.upper(), "short": True},
                            {"title": "Duration", "value": str(alert.duration), "short": True},
                        ],
                        "footer": "DFP Monitoring",
                        "ts": int(alert.starts_at.timestamp()),
                    }
                ],
            }

            if alert.value is not None:
                message["attachments"][0]["fields"].append({"title": "Value", "value": str(alert.value), "short": True})

            # Add labels
            for key, value in alert.labels.items():
                message["attachments"][0]["fields"].append({"title": key.capitalize(), "value": value, "short": True})

            # Send to Slack
            response = requests.post(self.webhook_url, json=message, timeout=10)
            response.raise_for_status()

            logger.debug(f"Alert sent to Slack: {alert.name}")

        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")

    def _get_color(self, severity: AlertSeverity) -> str:
        """Get color for severity level."""
        colors = {AlertSeverity.INFO: "#36a64f", AlertSeverity.WARNING: "#ff9900", AlertSeverity.CRITICAL: "#ff0000"}
        return colors.get(severity, "#808080")


@dataclass
class AlertRule:
    """Represents an alert rule."""

    name: str
    description: str
    condition: str  # Simple condition expression
    duration: str  # e.g., "5m", "10m"
    severity: AlertSeverity
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    def evaluate(self, metrics: dict[str, Any]) -> float | None:
        """
        Evaluate alert condition against metrics.

        Returns:
            Value that triggered the alert, or None if not triggered
        """
        try:
            # Simple condition evaluation
            # Format: "metric_name > threshold" or "metric_name == value"
            # This is a simplified implementation

            # Parse condition (basic support)
            condition = self.condition
            for metric_name, metric_value in metrics.items():
                condition = condition.replace(metric_name, str(metric_value))

            # Evaluate (use safe eval with limited scope)
            result = eval(condition, {"__builtins__": {}}, {})

            if result:
                # Extract value from metrics
                for metric_name in metrics:
                    if metric_name in self.condition:
                        return metrics[metric_name]
                return 1.0  # Condition met but no specific value

            return None

        except (NameError, SyntaxError) as e:
            # Metric doesn't exist yet - normal during startup
            logger.debug(f"Metric not available for alert rule {self.name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error evaluating alert rule {self.name}: {e}")
            return None


class AlertManager:
    """
    Manages alert rules and notifications.

    Example:
        >>> alert_manager = AlertManager('config/alerting.yaml')
        >>> alert_manager.start()
        >>> # Alerts will be evaluated and sent automatically
        >>> alert_manager.stop()
    """

    def __init__(self, config_path: str):
        """
        Initialize alert manager.

        Args:
            config_path: Path to alerting configuration YAML
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()

        self.rules: list[AlertRule] = []
        self.channels: list[AlertChannel] = []
        self.active_alerts: dict[str, Alert] = {}
        self.alert_history: list[Alert] = []

        self._lock = Lock()
        self._running = False
        self._thread: Thread | None = None

        self._load_rules()
        self._load_channels()

    def _load_config(self) -> dict[str, Any]:
        """Load alerting configuration."""
        if not self.config_path.exists():
            logger.warning(f"Alerting config not found: {self.config_path}")
            return {}

        with open(self.config_path) as f:
            return yaml.safe_load(f)

    def _load_rules(self):
        """Load alert rules from configuration."""
        rules_config = self.config.get("rules", [])

        for rule_cfg in rules_config:
            try:
                rule = AlertRule(
                    name=rule_cfg["name"],
                    description=rule_cfg["description"],
                    condition=rule_cfg["condition"],
                    duration=rule_cfg["duration"],
                    severity=AlertSeverity(rule_cfg["severity"]),
                    labels=rule_cfg.get("labels", {}),
                    annotations=rule_cfg.get("annotations", {}),
                    enabled=rule_cfg.get("enabled", True),
                )
                self.rules.append(rule)
                logger.debug(f"Loaded alert rule: {rule.name}")

            except Exception as e:
                logger.error(f"Failed to load alert rule: {e}")

    def _load_channels(self):
        """Load notification channels from configuration."""
        channels_config = self.config.get("alerting", {}).get("channels", [])

        for channel_cfg in channels_config:
            try:
                channel_type = channel_cfg["type"]

                if channel_type == "log":
                    channel = LogAlertChannel(level=channel_cfg.get("level", "ERROR"))

                elif channel_type == "file":
                    channel = FileAlertChannel(filepath=channel_cfg["path"])

                elif channel_type == "email" and channel_cfg.get("enabled", False):
                    channel = EmailAlertChannel(
                        smtp_host=channel_cfg["smtp_host"],
                        smtp_port=channel_cfg["smtp_port"],
                        smtp_user=channel_cfg["smtp_user"],
                        smtp_password=channel_cfg["smtp_password"],
                        from_address=channel_cfg["from_address"],
                        to_addresses=channel_cfg["to_addresses"],
                    )

                elif channel_type == "slack" and channel_cfg.get("enabled", False):
                    channel = SlackAlertChannel(webhook_url=channel_cfg["webhook_url"], channel=channel_cfg["channel"])

                else:
                    continue

                self.channels.append(channel)
                logger.debug(f"Loaded alert channel: {channel_type}")

            except Exception as e:
                logger.error(f"Failed to load alert channel: {e}")

    def start(self, interval: int = 30):
        """
        Start alert monitoring.

        Args:
            interval: Evaluation interval in seconds
        """
        if self._running:
            logger.warning("Alert manager already running")
            return

        self._running = True
        self._thread = Thread(target=self._run_loop, args=(interval,), daemon=True)
        self._thread.start()

        logger.info(f"Alert manager started (interval: {interval}s)")

    def stop(self):
        """Stop alert monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Alert manager stopped")

    def _run_loop(self, interval: int):
        """Main evaluation loop."""
        while self._running:
            try:
                self.evaluate_all()
            except Exception as e:
                logger.error(f"Error in alert evaluation loop: {e}")

            time.sleep(interval)

    def evaluate_all(self):
        """Evaluate all alert rules."""
        # Get current metrics
        collector = get_metrics_collector()
        metrics = collector.export_json()

        # Flatten metrics for easier access
        flat_metrics = {}
        for _metric_type, metric_data in metrics.items():
            if isinstance(metric_data, dict):
                flat_metrics.update(metric_data)

        # Evaluate each rule
        for rule in self.rules:
            if not rule.enabled:
                continue

            try:
                value = rule.evaluate(flat_metrics)

                if value is not None:
                    self._fire_alert(rule, value)
                else:
                    self._resolve_alert(rule.name)

            except (NameError, SyntaxError) as e:
                # Metric not yet available or invalid syntax - skip silently during startup
                logger.debug(f"Metric not available for rule {rule.name}: {e}")
            except Exception as e:
                # Log other errors (genuine issues)
                logger.error(f"Error evaluating alert rule {rule.name}: {e}")

    def _fire_alert(self, rule: AlertRule, value: float):
        """Fire an alert."""
        with self._lock:
            # Check if alert is already active
            if rule.name in self.active_alerts:
                # Update value
                self.active_alerts[rule.name].value = value
                return

            # Create new alert
            alert = Alert(
                name=rule.name,
                description=rule.description,
                severity=rule.severity,
                labels=rule.labels.copy(),
                annotations=rule.annotations.copy(),
                value=value,
            )

            self.active_alerts[rule.name] = alert
            self.alert_history.append(alert)

            # Send notifications
            for channel in self.channels:
                try:
                    channel.send(alert)
                except Exception as e:
                    logger.error(f"Failed to send alert via channel: {e}")

            logger.info(f"Alert fired: {rule.name} (value: {value})")

    def _resolve_alert(self, alert_name: str):
        """Resolve an alert."""
        with self._lock:
            if alert_name in self.active_alerts:
                alert = self.active_alerts[alert_name]
                alert.ends_at = datetime.now()
                del self.active_alerts[alert_name]

                logger.info(f"Alert resolved: {alert_name} (duration: {alert.duration})")

    def get_active_alerts(self) -> list[Alert]:
        """Get list of active alerts."""
        with self._lock:
            return list(self.active_alerts.values())

    def get_alert_history(self, limit: int = 100) -> list[Alert]:
        """Get alert history."""
        with self._lock:
            return self.alert_history[-limit:]


# Global alert manager instance
_global_alert_manager: AlertManager | None = None


def get_alert_manager(config_path: str = "config/alerting.yaml") -> AlertManager:
    """Get or create global alert manager."""
    global _global_alert_manager
    if _global_alert_manager is None:
        _global_alert_manager = AlertManager(config_path)
    return _global_alert_manager
