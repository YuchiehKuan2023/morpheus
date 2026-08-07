# NVIDIA Morpheus DFP Reference Code Paths

This document provides paths to key NVIDIA Morpheus reference implementations that guide our DFP PoC development.

**Local Repository**: `/morpheus-dfp/nv-morpheus/`

---

## Core DFP Modules

### DFP Python Package

**Base Path**: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/`

#### Stage Modules (`stages/`)

- **`dfp_file_to_df.py`** - Convert files to DataFrame

  - Path: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_file_to_df.py`
  - Purpose: Load JSON/CSV files into Pandas DataFrames
  - Reference for: Phase 3.1.2 (File I/O)

- **`dfp_preprocessing.py`** - Data preprocessing and feature engineering

  - Path: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_preprocessing.py`
  - Purpose: Temporal features, derived features (new_city_counter, locincrement, etc.)
  - Reference for: Phase 3.2.1 (Preprocessing Module)

- **`dfp_split_users.py`** - Split data by user_id

  - Path: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_split_users.py`
  - Purpose: Create per-user DataFrames for individual model training
  - Reference for: Phase 3.3.1 (User Splitting)

- **`dfp_rolling_window.py`** - Rolling window aggregation
  - Path: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_rolling_window.py`
  - Purpose: Time-based windowing (24H windows, 12H slide)
  - Reference for: Phase 3.4.1 (Rolling Window Module)

#### Module Implementations (`modules/`)

- **`dfp_data_prep.py`** - Data preparation for model input

  - Path: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_data_prep.py`
  - Purpose: Convert processed data to model-ready format
  - Reference for: Phase 3.5.1 (Data Prep Module)

- **`dfp_training.py`** - Model training module

  - Path: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_training.py`
  - Purpose: dfencoder training loop, per-user model training
  - Reference for: Phase 5.2.1 (Training Module)

- **`dfp_inference.py`** - Inference and anomaly scoring

  - Path: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_inference.py`
  - Purpose: Model loading, reconstruction, z-score calculation
  - Reference for: Phase 6.1.1 (Inference Module)

- **`mlflow_model_writer.py`** - MLflow model persistence
  - Path: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/mlflow_model_writer.py`
  - Purpose: Save models to MLflow with metadata
  - Reference for: Phase 5.3.1 (MLflow Writer)

---

## dfencoder AutoEncoder Model

### Model Implementation

**Base Path**: `/nv-morpheus/python/morpheus/morpheus/models/dfencoder/`

- **`autoencoder.py`** - Core AutoEncoder implementation

  - Path: `/nv-morpheus/python/morpheus/morpheus/models/dfencoder/autoencoder.py`
  - Purpose: PyTorch AutoEncoder architecture (encoder, decoder, loss)
  - Reference for: Phase 5.1.1 (Model Integration)
  - Key Classes: `AutoEncoder`, `Encoder`, `Decoder`

- **`dataframe.py`** - DataFrame handling for dfencoder

  - Path: `/nv-morpheus/python/morpheus/morpheus/models/dfencoder/dataframe.py`
  - Purpose: Convert DataFrame to tensor format
  - Reference for: Phase 3.5.1, Phase 5.2.1

- **`scalers.py`** - Feature scaling utilities
  - Path: `/nv-morpheus/python/morpheus/morpheus/models/dfencoder/scalers.py`
  - Purpose: Normalization for numerical features
  - Reference for: Phase 3.2.2 (Feature engineering)

---

## Example Pipelines

### Production DFP Example

**Base Path**: `/nv-morpheus/examples/digital_fingerprinting/production/`

- **Training Pipeline**

  - Path: `/nv-morpheus/examples/digital_fingerprinting/production/morpheus/dfp/training_pipeline.py`
  - Purpose: Complete end-to-end training pipeline
  - Reference for: Phase 5.5.1 (Training Orchestration)

- **Inference Pipeline**

  - Path: `/nv-morpheus/examples/digital_fingerprinting/production/morpheus/dfp/inference_pipeline.py`
  - Purpose: Complete end-to-end inference pipeline
  - Reference for: Phase 6.5.1 (Inference Orchestration)

- **Configuration Files**
  - Path: `/nv-morpheus/examples/digital_fingerprinting/production/config/`
  - Files:
    - `dfp_config_azure.json` - Azure AD log configuration
    - `dfp_config_duo.json` - Duo Authentication log configuration
  - Reference for: Phase 1 (Config files), Phase 2 (Data schema)

### Data Schemas

**Base Path**: `/nv-morpheus/examples/digital_fingerprinting/production/morpheus/dfp/schemas/`

- **Azure AD Schema**

  - Path: `/nv-morpheus/examples/digital_fingerprinting/production/morpheus/dfp/schemas/azure_ad_schema.json`
  - Purpose: Azure Active Directory log structure
  - Reference for: Phase 2.1.1 (Data Schema), Phase 2.2.1 (Synthetic Generator)

- **Duo Authentication Schema**
  - Path: `/nv-morpheus/examples/digital_fingerprinting/production/morpheus/dfp/schemas/duo_schema.json`
  - Purpose: Duo Authentication log structure
  - Reference for: Phase 2.1.1 (Alternative schema reference)

---

## Control Messages

### Control Message Implementation

**Base Path**: `/nv-morpheus/python/morpheus/morpheus/messages/`

- **`control_message.py`** - Control message class
  - Path: `/nv-morpheus/python/morpheus/morpheus/messages/control_message.py`
  - Purpose: Message-based pipeline routing (train vs inference)
  - Reference for: Phase 4.2.1 (Control Message Handler)

---

## Documentation References

### Official NVIDIA Morpheus Documentation

1. **Digital Fingerprinting Developer Guide**

   - URL: <https://docs.nvidia.com/morpheus/developer_guide/guides/5_digital_fingerprinting.html>
   - Topics: DFP overview, architecture, AutoEncoder approach

2. **Modular Pipeline Guide**

   - URL: <https://docs.nvidia.com/morpheus/developer_guide/guides/10_modular_pipeline_digital_fingerprinting.html>
   - Topics: Module structure, control messages, pipeline orchestration

3. **DFP Training Module Reference**

   - URL: <https://docs.nvidia.com/morpheus/modules/examples/digital_fingerprinting/dfp_training.html>
   - Topics: Training parameters, configuration

4. **DFP Inference Module Reference**
   - URL: <https://docs.nvidia.com/morpheus/modules/examples/digital_fingerprinting/dfp_inference.html>
   - Topics: Inference parameters, anomaly scoring

### GitHub Repository

- **NVIDIA Morpheus Repository**
  - URL: <https://github.com/nv-morpheus/Morpheus>
  - Branch: `branch-25.10`
  - Local clone: `/nv-morpheus/`

---

## Quick Reference by Implementation Phase

### Phase 2: Data Generation

- Azure AD Schema: `/nv-morpheus/examples/digital_fingerprinting/production/morpheus/dfp/schemas/azure_ad_schema.json`
- Config Examples: `/nv-morpheus/examples/digital_fingerprinting/production/config/`

### Phase 3: Data Processing

- Preprocessing: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_preprocessing.py`
- User Splitting: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_split_users.py`
- Rolling Window: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/stages/dfp_rolling_window.py`
- Data Prep: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_data_prep.py`

### Phase 4: Control Messages

- Control Message: `/nv-morpheus/python/morpheus/morpheus/messages/control_message.py`

### Phase 5: Training Pipeline

- dfencoder Model: `/nv-morpheus/python/morpheus/morpheus/models/dfencoder/autoencoder.py`
- Training Module: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_training.py`
- MLflow Writer: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/mlflow_model_writer.py`
- Training Pipeline: `/nv-morpheus/examples/digital_fingerprinting/production/morpheus/dfp/training_pipeline.py`

### Phase 6: Inference Pipeline

- Inference Module: `/nv-morpheus/python/morpheus_dfp/morpheus_dfp/modules/dfp_inference.py`
- Inference Pipeline: `/nv-morpheus/examples/digital_fingerprinting/production/morpheus/dfp/inference_pipeline.py`

---

## Notes

- All paths are relative to the local Morpheus repository clone
- Reference code should guide implementation but NOT be copied directly
- Follow NVIDIA's architecture patterns but adapt for PoC requirements
- Consult official documentation for detailed API usage and best practices
- When in doubt, study the production examples in `/examples/digital_fingerprinting/production/`

---

**Last Updated**: 2025-11-07  
**Morpheus Version**: 25.10  
**Branch**: branch-25.10
