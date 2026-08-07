"""Retrain status and trigger endpoints."""

import logging

import psycopg2.extras
from auth_utils import get_current_user
from db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status")
def retrain_status(
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get recent retrain job history (DFP + classifiers)."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # DFP retrain jobs
                cur.execute(
                    """SELECT job_id::text, user_id, retrain_type, status,
                              new_clean_events, total_training_events,
                              new_model_version, mlflow_run_id,
                              created_at, started_at, completed_at, error_message
                       FROM dfp_retrain_jobs
                       ORDER BY created_at DESC
                       LIMIT %s""",
                    (limit,),
                )
                dfp_jobs = []
                for r in cur.fetchall():
                    row = dict(r)
                    for k in ("created_at", "started_at", "completed_at"):
                        if row.get(k):
                            row[k] = row[k].isoformat()
                    dfp_jobs.append(row)

                # Classifier retrain log
                cur.execute(
                    """SELECT id, classifier_type, anomalies_at_retrain,
                              model_path, mlflow_run_id, status,
                              duration_seconds, error_message,
                              started_at, completed_at, created_at
                       FROM classifier_retrain_log
                       ORDER BY created_at DESC
                       LIMIT %s""",
                    (limit,),
                )
                clf_jobs = []
                for r in cur.fetchall():
                    row = dict(r)
                    for k in ("started_at", "completed_at", "created_at"):
                        if row.get(k):
                            row[k] = row[k].isoformat()
                    clf_jobs.append(row)

        return {"dfp_jobs": dfp_jobs, "classifier_jobs": clf_jobs}
    except Exception as e:
        logger.error(f"Error fetching retrain status: {e}")
        raise HTTPException(status_code=500, detail="Database error") from e


@router.post("/trigger/{user_id}")
def trigger_dfp_retrain(user_id: str, user: dict = Depends(get_current_user)):
    """Manually trigger a DFP retrain for a specific user."""
    from modules.ai.feedback.dfp_retrain_runner import DFPRetrainRunner

    runner = DFPRetrainRunner()
    job_id = runner.trigger_for_user(user_id)

    if job_id is None:
        raise HTTPException(status_code=409, detail="A retrain job is already pending or running for this user")

    return {"status": "ok", "job_id": job_id, "user_id": user_id}


@router.post("/trigger-classifier/{classifier_type}")
def trigger_classifier_retrain(classifier_type: str, user: dict = Depends(get_current_user)):
    """Manually trigger a classifier retrain (risk_scorer or root_cause)."""
    valid_types = {"risk_scorer", "root_cause"}
    if classifier_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid classifier type. Must be one of: {', '.join(sorted(valid_types))}",
        )

    from modules.ai.feedback.classifier_retrainer import ClassifierRetrainer

    retrainer = ClassifierRetrainer()
    result = retrainer.force_retrain(classifier_type)

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    return {"status": "ok", "classifier_type": classifier_type, **result}
