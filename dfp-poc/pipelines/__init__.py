"""
DFP Pipelines Package

This package contains the main pipeline orchestration modules following NVIDIA Morpheus
DFP modular architecture patterns.

Modules:
- pipeline: Main orchestrator with CLI interface (training and inference modes)
- training_pipeline: NVIDIA dfp_training_pipe modular pattern implementation
- inference_pipeline: NVIDIA dfp_inference_pipe real-time streaming pattern

The modular pattern implements NVIDIA's recommended approach:
- Separate training and inference pipelines
- Shared cache directory (aggregate mode for both)
- Single preprocessing (after rolling window)
- Real-time streaming inference with Kafka

Architecture Reference:
- NVIDIA Morpheus DFP Documentation
- python/morpheus_dfp/morpheus_dfp/modules/dfp_training_pipe.py
- python/morpheus_dfp/morpheus_dfp/modules/dfp_inference_pipe.py
- docs/implementation/modular_architecture.md
"""

from pipelines.inference_pipeline import DFPInferencePipeline
from pipelines.pipeline import DFPPipeline
from pipelines.training_pipeline import DFPTrainingPipeline

__all__ = [
    "DFPPipeline",
    "DFPTrainingPipeline",
    "DFPInferencePipeline",
]
