# NVIDIA Morpheus DFP AutoEncoder Module

## Overview

This module contains the **official NVIDIA Morpheus Digital Fingerprinting (DFP) AutoEncoder implementation**, adapted for CPU/MPS execution environments. These are **not custom implementations** but rather direct adaptations of NVIDIA's production-grade DFP components.

## Source and Provenance

**Original Source:**

- Repository: [`nv-morpheus/morpheus`](https://github.com/nv-morpheus/morpheus)
- Branch: `branch-25.10`
- Path: `python/morpheus_dfp/morpheus_dfp/modules/dfp_data_prep.py`
- License: Apache License 2.0

**Adaptation Scope:**
These modules have been adapted **solely** to enable execution on non-CUDA hardware (CPU, Apple Silicon MPS) while maintaining complete functional parity with NVIDIA's reference implementation. No algorithmic or architectural modifications have been made.

## Module Contents

### Core Components

- **`autoencoder.py`** - NVIDIA's AutoEncoder architecture for behavioral anomaly detection
- **`ae_module.py`** - PyTorch module implementation
- **`dataframe.py`** - DataFrame utilities for encoder operations
- **`dataloader.py`** - Data loading and batching logic
- **`distributed_ae.py`** - Distributed training support (DistributedDataParallel)
- **`logging.py`** - Training and inference logging utilities

### Key Features (from NVIDIA Implementation)

1. **Hybrid Neural Network Architecture**

   - Separate processing paths for numerical, binary, and categorical features
   - Embedding layers for high-cardinality categorical features
   - Configurable encoder/decoder layer dimensions

2. **Robust Loss Computation**

   - Mean Squared Error (MSE) for numerical features
   - Binary Cross-Entropy (BCE) for binary features
   - Categorical Cross-Entropy (CCE) for categorical features
   - Per-feature loss tracking and z-score normalization

3. **Production-Ready Training**

   - Early stopping with patience thresholds
   - Learning rate decay schedules
   - Distributed training via PyTorch DDP
   - Comprehensive logging and checkpointing

4. **Inference Optimization**
   - Batch processing with configurable batch sizes
   - Per-feature anomaly score computation
   - StandardScaler and ModifiedZScaler options
   - Feature-level reconstruction tracking

## Modifications Made

**Hardware Compatibility Only:**

- Removed CUDA-specific code paths
- Added CPU and Apple MPS (Metal Performance Shaders) device support
- Maintained all algorithmic logic, loss functions, and model architecture

**No Changes to:**

- Model architecture (encoder/decoder layers)
- Loss computation (MSE, BCE, CCE)
- Feature processing (numerical, binary, categorical)
- Training procedures (optimizer, scheduler, early stopping)
- Inference logic (z-score computation, anomaly detection)
- Data preparation and preprocessing

## Important: Do Not Modify

**CRITICAL NOTICE:**

These modules should **NOT** be modified unless:

1. **Updating to newer NVIDIA Morpheus releases** - To incorporate upstream improvements
2. **Fixing critical bugs** - That are also being addressed in the upstream repository
3. **Adding hardware compatibility** - For new execution environments while maintaining functional equivalence

**Rationale:**

- Preserves compatibility with NVIDIA's reference implementation
- Ensures reproducibility of results with official DFP documentation
- Maintains support for future upstream updates
- Guarantees production-grade reliability and testing coverage

## Validation Against NVIDIA Reference

These modules have been validated to produce equivalent results to NVIDIA's CUDA implementation:

- Model training convergence
- Loss statistics (mean, std, distribution)
- Anomaly score computation
- Feature-level z-scores
- Threshold-based detection accuracy

## Usage Example

```python
from modules.dfencoder import AutoEncoder

# Initialize with NVIDIA-standard parameters
model = AutoEncoder(
    encoder_layers=[512, 500],
    decoder_layers=[512],
    activation='relu',
    learning_rate=0.01,
    epochs=100,
    batch_size=1024,
    loss_scaler='standard'  # NVIDIA default
)

# Train (NVIDIA API)
model.fit(training_data)

# Inference (NVIDIA API)
results = model.get_results(test_data, return_abs=True)
```

## References

- [NVIDIA Morpheus Documentation](https://docs.nvidia.com/morpheus/)
- [Digital Fingerprinting Guide](https://docs.nvidia.com/morpheus/developer_guide/guides/5_digital_fingerprinting.html)
- [GitHub Repository](https://github.com/nv-morpheus/morpheus)

## Version Information

- **NVIDIA Morpheus Version:** 25.10
- **Adaptation Date:** November 2025
- **Python Version:** 3.12+
- **PyTorch Version:** 2.0+

## License

Apache License 2.0 (inherited from NVIDIA Morpheus)

---

**Maintainer Note:** When in doubt about module behavior, consult the official NVIDIA Morpheus documentation and reference implementation. These modules are production-tested by NVIDIA and should be treated as authoritative.
