#!/usr/bin/env python3
"""
Retrain Runner Entrypoint
=========================

Runs both DFP autoencoder retraining and classifier retraining:

    1. DFP Retrain Runner — polls dfp_retrain_jobs for pending per-user
       DFP model retrain requests and executes them via the standard
       DFPTrainingPipeline.

    2. Classifier Retrainer — checks whether enough new classified
       anomalies have accumulated to justify retraining the XGBoost
       risk scorer and/or DistilBERT root cause classifier.

Usage
-----
    # Poll mode (default) — runs continuously:
    python scripts/run_retrain_runner.py

    # Single pass — process pending jobs and exit:
    python scripts/run_retrain_runner.py --once

    # Classifiers only (skip DFP):
    python scripts/run_retrain_runner.py --classifiers-only

    # DFP only (skip classifiers):
    python scripts/run_retrain_runner.py --dfp-only

    # Force classifier retrain regardless of threshold:
    python scripts/run_retrain_runner.py --once --force-classifiers

Environment variables (all optional — defaults shown)
------------------------------------------------------
    POSTGRES_HOST                 localhost
    POSTGRES_PORT                 5433
    POSTGRES_DB                   dfp_ai
    POSTGRES_USER                 dfp_ai
    POSTGRES_PASSWORD             (required — set in .env)
    MLFLOW_TRACKING_URI           http://localhost:5001
    RETRAIN_POLL_INTERVAL         60          (seconds)
    CLASSIFIER_RETRAIN_THRESHOLD  50          (new classified anomalies)
    CLASSIFIER_CHECK_INTERVAL     3600        (seconds — check classifiers every N seconds)
    FORECAST_RETRAIN_THRESHOLD    100         (new anomalies to trigger forecast retrain)

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2026-04-29
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path and .env is loaded before any imports
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-35s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("run_retrain_runner")

# ---------------------------------------------------------------------------
# Late imports (after sys.path + env are set)
# ---------------------------------------------------------------------------
from modules.ai.feedback.classifier_retrainer import ClassifierRetrainer  # noqa: E402
from modules.ai.feedback.dfp_retrain_runner import DFPRetrainRunner  # noqa: E402
from modules.ai.forecasting.prophet_forecaster import AnomalyForecaster  # noqa: E402

POLL_INTERVAL = int(os.getenv("RETRAIN_POLL_INTERVAL", "60"))
CLASSIFIER_CHECK_INTERVAL = int(os.getenv("CLASSIFIER_CHECK_INTERVAL", "3600"))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Retrain runner — DFP + classifiers")
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--dfp-only", action="store_true", help="Only run DFP retraining")
    parser.add_argument("--classifiers-only", action="store_true", help="Only run classifier retraining")
    parser.add_argument("--forecast-only", action="store_true", help="Only run forecast retraining")
    parser.add_argument("--force-classifiers", action="store_true", help="Force classifier retrain (ignore threshold)")
    parser.add_argument("--force-forecast", action="store_true", help="Force forecast retrain (ignore threshold)")
    args = parser.parse_args()

    only_flags = [args.dfp_only, args.classifiers_only, args.forecast_only]
    if sum(only_flags) > 1:
        parser.error("--dfp-only, --classifiers-only, and --forecast-only are mutually exclusive")

    run_dfp = not args.classifiers_only and not args.forecast_only
    run_classifiers = not args.dfp_only and not args.forecast_only
    run_forecast = not args.dfp_only and not args.classifiers_only

    logger.info("Retrain runner starting")
    logger.info(f"  DFP retraining       : {'enabled' if run_dfp else 'disabled'}")
    logger.info(f"  Classifier retraining: {'enabled' if run_classifiers else 'disabled'}")
    logger.info(f"  Forecast retraining  : {'enabled' if run_forecast else 'disabled'}")
    logger.info(f"  Mode                 : {'single pass' if args.once else 'polling'}")

    dfp_runner = DFPRetrainRunner() if run_dfp else None
    clf_retrainer = ClassifierRetrainer() if run_classifiers else None
    forecaster = AnomalyForecaster() if run_forecast else None

    if args.once:
        # Single pass
        if dfp_runner:
            count = dfp_runner.run_once()
            logger.info(f"DFP: processed {count} job(s)")

        if clf_retrainer:
            if args.force_classifiers:
                for clf in ("risk_scorer", "root_cause"):
                    logger.info(f"Force retraining {clf}…")
                    result = clf_retrainer.force_retrain(clf)
                    logger.info(f"  {clf}: {result}")
            else:
                results = clf_retrainer.check_and_retrain_all()
                for clf, res in results.items():
                    logger.info(f"  {clf}: {res}")

        if forecaster:
            if args.force_forecast:
                logger.info("Force retraining forecast model…")
                result = forecaster.force_retrain()
            else:
                result = forecaster.check_and_retrain()
            logger.info(f"  forecast: {result}")
        return

    # Polling mode
    if dfp_runner and not run_classifiers and not run_forecast:
        # DFP-only mode — use the built-in poll loop
        dfp_runner.poll_and_run()
        return

    # Combined mode — interleave DFP polling with periodic classifier + forecast checks
    last_classifier_check = 0.0
    last_forecast_check = 0.0
    _running = True

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal _running
        logger.info("Received signal %d — stopping after current iteration", signum)
        _running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(f"Polling every {POLL_INTERVAL}s (classifier/forecast check every {CLASSIFIER_CHECK_INTERVAL}s)")
    try:
        while _running:
            # 1. Check for pending DFP jobs
            if dfp_runner:
                if dfp_runner.process_next_job():
                    continue  # Check for more DFP jobs before sleeping

            now = time.monotonic()

            # 2. Periodically check classifier thresholds
            if clf_retrainer and (now - last_classifier_check) >= CLASSIFIER_CHECK_INTERVAL:
                logger.info("Checking classifier retrain thresholds…")
                results = clf_retrainer.check_and_retrain_all()
                for clf, res in results.items():
                    if res.get("retrained"):
                        logger.info(f"  {clf}: retrained successfully")
                    else:
                        delta = res.get("delta", "?")
                        reason = res.get("reason", f"delta={delta}")
                        logger.info(f"  {clf}: {reason}")
                last_classifier_check = now

            # 3. Periodically check forecast retrain threshold
            if forecaster and (now - last_forecast_check) >= CLASSIFIER_CHECK_INTERVAL:
                logger.info("Checking forecast retrain threshold…")
                result = forecaster.check_and_retrain()
                if result.get("retrained"):
                    logger.info("  forecast: retrained successfully")
                else:
                    delta = result.get("delta", "?")
                    logger.info(f"  forecast: delta={delta}")
                last_forecast_check = now

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Retrain runner stopped by KeyboardInterrupt")


if __name__ == "__main__":
    main()
