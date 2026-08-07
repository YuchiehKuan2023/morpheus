"""
DFP Training Module

This module contains training-related components for the Digital Fingerprinting
Platform, including AutoEncoder training, MLflow integration, and evaluation.

Components:
- DFPAutoEncoder: Wrapper around NVIDIA Morpheus dfencoder AutoEncoder
- DFPTrainer: Core training module for per-user model training
- MLflowModelWriter: Model persistence and registry integration
- TrainingEvaluator: Baseline statistics computation for anomaly detection

Based on NVIDIA Morpheus DFP implementation:
- python/morpheus_dfp/morpheus_dfp/modules/dfp_training.py
- python/morpheus_dfp/morpheus_dfp/modules/mlflow_model_writer.py
"""

from .autoencoder_wrapper import DFPAutoEncoder
from .dfp_trainer import DFPTrainer
from .evaluation import TrainingEvaluator
from .mlflow_model_writer import MLflowModelWriter

__all__ = ["DFPAutoEncoder", "DFPTrainer", "MLflowModelWriter", "TrainingEvaluator"]
