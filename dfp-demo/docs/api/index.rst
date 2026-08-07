API Reference
=============

This section provides detailed API documentation for all modules in the Morpheus DFP platform.

.. toctree::
   :maxdepth: 2
   :caption: Modules:

   preprocessing
   training
   inference
   io
   control
   utils

Module Overview
---------------

The platform is organized into the following modules:

**Preprocessing**: Data preprocessing and feature engineering

- ``dfp_preprocessing`` - Schema-based preprocessing
- ``geographic_features`` - Travel velocity calculations  
- ``rolling_window`` - Historical data aggregation
- ``data_prep`` - Feature selection and preparation
- ``user_splitting`` - Per-user data partitioning

**Training**: Model training and management

- ``dfp_trainer`` - AutoEncoder training with PyTorch
- ``mlflow_model_writer`` - Model versioning and registration

**Inference**: Real-time anomaly detection

- ``dfp_inference`` - Model loading and z-score calculation
- ``filter_detections`` - Binary threshold filtering

**I/O**: Input/output operations

- ``file_to_df`` - File loading with schema validation
- ``kafka_consumer`` - Kafka message consumption
- ``kafka_producer`` - Kafka message production

**Control**: Pipeline communication

- ``control_message`` - Message passing between modules

**Utilities**: Helper functions and tools

- ``metrics_utils`` - Prometheus metrics tracking
- ``mlflow_utils`` - MLflow integration utilities
