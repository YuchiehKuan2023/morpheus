#!/usr/bin/env python3
"""Check feature loss statistics in all trained models."""

import glob
import os

import mlflow
import torch
from mlflow.tracking import MlflowClient

# Connect to MLflow to get model names
mlflow.set_tracking_uri("http://localhost:5001")
client = MlflowClient()

# Find all model paths
model_paths = sorted(glob.glob("data/mlflow/models/*/artifacts/data/model.pth"), key=os.path.getmtime, reverse=True)

print(f"Found {len(model_paths)} models\n")
print("=" * 80)

all_zero_std = 0
all_low_std = 0
all_healthy = 0

for idx, model_path in enumerate(model_paths, 1):
    model_id = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(model_path))))

    # Try to find model name from MLflow
    try:
        model_versions = client.search_model_versions(f"source_path LIKE '%{model_id}%'")
        if model_versions:
            model_name = model_versions[0].name.replace("DFP-", "")
        else:
            model_name = "Unknown"
    except Exception:
        model_name = "Unknown"

    print(f"\n{idx}. {model_name}")
    print(f"   Model ID: {model_id}")
    print(f"   Modified: {os.path.getmtime(model_path)}")

    # Load model
    ae = torch.load(model_path, map_location="cpu", weights_only=False)

    if hasattr(ae, "feature_loss_stats"):
        print(f"   Features: {len(ae.feature_loss_stats)}")

        zero_std_count = 0
        low_std_count = 0

        print("   " + "-" * 76)
        for feat, stats in sorted(ae.feature_loss_stats.items()):
            scaler = stats["scaler"]
            mean = float(scaler.mean)
            std = float(scaler.std)

            if std < 0.001:
                indicator = "ERROR: ZERO (near-zero: < 0.001)"
                zero_std_count += 1
            elif std < 0.01:
                indicator = "WARNING: LOW (< 0.01)"
                low_std_count += 1
            else:
                indicator = "SUCCESS: HEALTHY (>= 0.01)"

            print(f"   {indicator}  {feat:30s}: mean={mean:8.6f}, std={std:8.6f}")

        print("   " + "-" * 76)
        total = len(ae.feature_loss_stats)
        healthy = total - zero_std_count - low_std_count

        all_zero_std += zero_std_count
        all_low_std += low_std_count
        all_healthy += healthy

        if zero_std_count == 0 and low_std_count == 0:
            print(f"ALL {total} features healthy!")
        else:
            print(f"Zero: {zero_std_count}, Low: {low_std_count}, Healthy: {healthy}/{total}")
    else:
        print("No feature_loss_stats found")

print("\n" + "=" * 80)
print("OVERALL SUMMARY ACROSS ALL MODELS:")
print(f"  Near-zero std (<0.001): {all_zero_std}")
print(f"  Low std (<0.01):        {all_low_std}")
print(f"  Healthy std (>=0.01):   {all_healthy}")

if all_zero_std == 0 and all_low_std == 0:
    print("\nALL MODELS HAVE HEALTHY VARIANCE!")
    print("   Should produce normal z-scores (<5) for normal events")
else:
    print(f"\n{all_zero_std + all_low_std} total features have concerning variance")
    print("   May produce extreme z-scores")
