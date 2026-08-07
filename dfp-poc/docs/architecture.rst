Architecture
============

This document provides a high-level overview of the Morpheus DFP platform architecture.

System Overview
---------------

The platform follows NVIDIA Morpheus patterns for modular, scalable anomaly detection:

.. code-block:: text

   ┌─────────────────────────────────────────────────────────────┐
   │                     Data Sources                             │
   │              (Azure AD, Kafka, Files)                        │
   └──────────────────┬──────────────────────────────────────────┘
                      │
   ┌──────────────────▼──────────────────────────────────────────┐
   │              Training Pipeline                               │
   │  ┌──────────┐  ┌────────────┐  ┌────────────┐  ┌─────────┐ │
   │  │ DFP_     │→│  Geographic │→│  Rolling   │→│  DFP    │ │
   │  │ PREPROC  │  │  Features   │  │  Window    │  │ Training│ │
   │  └──────────┘  └────────────┘  └────────────┘  └─────────┘ │
   │                                                     ↓        │
   │                                              ┌──────────────┐ │
   │                                              │   MLflow     │ │
   │                                              │  (Models)    │ │
   │                                              └──────────────┘ │
   └─────────────────────────────────────────────────────────────┘
                                                     
   ┌─────────────────────────────────────────────────────────────┐
   │              Inference Pipeline                              │
   │  ┌──────────┐  ┌────────────┐  ┌────────────┐  ┌─────────┐ │
   │  │ Kafka    │→│  DFP       │→│  DFP       │→│  Filter │ │
   │  │ Consumer │  │  Preproc   │  │  Inference │  │  Detect │ │
   │  └──────────┘  └────────────┘  └────────────┘  └─────────┘ │
   │                                                     ↓        │
   │                                              ┌──────────────┐ │
   │                                              │    Output    │ │
   │                                              │ (Detections) │ │
   │                                              └──────────────┘ │
   └─────────────────────────────────────────────────────────────┘

Core Components
---------------

Training Pipeline
~~~~~~~~~~~~~~~~~

Batch processing for model training:

1. **DFP_PREPROC**: Load and split data by user
2. **Geographic Features**: Calculate travel velocity and distance
3. **Rolling Window**: Build 60-day historical windows (aggregate mode)
4. **Data Prep**: Apply feature schema and create increment features
5. **DFP Training**: Train AutoEncoder per user
6. **MLflow**: Save and register models

Inference Pipeline
~~~~~~~~~~~~~~~~~~

Real-time streaming for anomaly detection:

1. **Kafka Consumer**: Receive events from Kafka topic
2. **DFP Preprocessing**: Apply feature schema and transformations
3. **DFP Inference**: Load models and compute z-scores
4. **FilterDetections**: Apply binary threshold filtering
5. **Output**: Send anomalies to downstream systems

Module Architecture
-------------------

Preprocessing Module
~~~~~~~~~~~~~~~~~~~~

Data preprocessing and feature engineering:

- ``dfp_preprocessing``: Schema-based preprocessing
- ``geographic_features``: Travel velocity calculations
- ``rolling_window``: Historical data aggregation
- ``data_prep``: Feature selection and preparation
- ``user_splitting``: Per-user data partitioning

Training Module
~~~~~~~~~~~~~~~

Model training and management:

- ``dfp_trainer``: AutoEncoder training with PyTorch
- ``mlflow_model_writer``: Model versioning and registration

Inference Module
~~~~~~~~~~~~~~~~

Real-time anomaly detection:

- ``dfp_inference``: Model loading and z-score calculation
- ``filter_detections``: Binary threshold filtering

I/O Module
~~~~~~~~~~

Data input/output operations:

- ``file_to_df``: File loading with schema validation
- ``kafka_consumer``: Kafka message consumption
- ``kafka_producer``: Kafka message production

Control Module
~~~~~~~~~~~~~~

Pipeline communication:

- ``control_message``: Message passing between modules

Utilities Module
~~~~~~~~~~~~~~~~

Helper functions and tools:

- ``metrics_utils``: Prometheus metrics tracking
- ``mlflow_manager``: MLflow experiment management

Data Flow
---------

Training Flow
~~~~~~~~~~~~~

1. Raw events loaded from files
2. Schema applied and nulls filtered
3. Split by user (per-user models)
4. Geographic features calculated (travel_speed_kmph)
5. Rolling window built (60-day aggregate)
6. Feature schema applied (increments, categories)
7. AutoEncoder trained on historical patterns
8. Model saved to MLflow with versioning

Inference Flow
~~~~~~~~~~~~~~

1. Events consumed from Kafka in real-time
2. Schema applied and features calculated
3. User-specific model loaded from MLflow
4. Z-scores computed for each feature
5. Mean absolute z-score (mean_abs_z) calculated
6. Binary threshold filter applied (default: 2.0)
7. Only anomalies output (NVIDIA standard)

Feature Engineering
-------------------

Behavioral Features
~~~~~~~~~~~~~~~~~~~

Increment features track changes between events:

- ``appincrement``: Application access patterns
- ``logcountincrement``: Login frequency changes
- ``locincrement``: Location changes

Geographic Features
~~~~~~~~~~~~~~~~~~~

Travel patterns and velocity:

- ``travel_speed_kmph``: Speed between consecutive locations
- ``distance_km``: Distance traveled
- ``ts_delta_hour``: Time between events

These features are included in AutoEncoder training to learn normal travel patterns.

Model Architecture
------------------

AutoEncoder Design
~~~~~~~~~~~~~~~~~~

- **Encoder**: [Input → 512 → 500]
- **Decoder**: [500 → 512 → Output]
- **Activation**: ReLU
- **Optimizer**: SGD with learning rate decay
- **Loss**: MSE (reconstruction error)

Training Strategy
~~~~~~~~~~~~~~~~~

- **Per-user models**: Personalized anomaly detection
- **Generic fallback**: For users with insufficient data
- **60-day windows**: Balance history and relevance
- **Validation split**: 10% for early stopping

Deployment
----------

Service Architecture
~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   ┌─────────────────────────────────────────────────────────────┐
   │                    Docker Compose Stack                      │
   │                                                              │
   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
   │  │  Kafka   │  │ MLflow   │  │Prometheus│  │ Grafana  │   │
   │  │Zookeeper │  │          │  │          │  │          │   │
   │  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
   │                                                              │
   └─────────────────────────────────────────────────────────────┘
              ↑              ↑              ↑              ↑
              │              │              │              │
   ┌──────────┴──────────────┴──────────────┴──────────────┴────┐
   │              DFP Pipelines (Python)                          │
   │  ┌────────────────────┐  ┌──────────────────────┐          │
   │  │ Training Pipeline  │  │ Inference Pipeline   │          │
   │  │   (Batch Job)      │  │  (Streaming Service) │          │
   │  └────────────────────┘  └──────────────────────┘          │
   └─────────────────────────────────────────────────────────────┘

Scalability
-----------

Horizontal Scaling
~~~~~~~~~~~~~~~~~~

- **Kafka partitioning**: Parallel consumption
- **Per-user models**: Independent processing
- **Stateless inference**: No shared state
- **Cache-based training**: Incremental updates

Performance Optimizations
~~~~~~~~~~~~~~~~~~~~~~~~~

- **Batch processing**: Process multiple events together
- **GPU acceleration**: CuPy/CuDF for preprocessing
- **Model caching**: In-memory model storage
- **Async I/O**: Non-blocking Kafka operations

Monitoring
----------

Metrics Collection
~~~~~~~~~~~~~~~~~~

- **Events processed**: Total throughput
- **Anomaly rate**: Detection percentage
- **Processing latency**: Per-stage timing
- **Model performance**: Loss and accuracy

Dashboards
~~~~~~~~~~

- **Pipeline metrics**: Throughput and errors
- **Model metrics**: Training and inference performance
- **System metrics**: CPU, memory, disk usage
- **Anomaly dashboard**: Detection visualization

For more details, see:

- :doc:`getting_started` for deployment instructions
- :doc:`api/index` for module documentation
- :doc:`examples` for usage examples
