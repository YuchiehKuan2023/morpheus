Morpheus DFP Documentation
==========================

Welcome to the Morpheus Digital Fingerprinting Platform documentation. This platform implements NVIDIA Morpheus DFP patterns for user behavior anomaly detection using unsupervised AutoEncoder models.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   getting_started
   architecture
   api/index
   examples
   configuration
   deployment

Overview
--------

The Morpheus DFP platform provides:

* **Behavioral Learning**: AutoEncoder-based anomaly detection
* **Geographic Features**: Travel velocity and location analysis
* **Real-time Processing**: Kafka-based streaming inference
* **Model Management**: MLflow integration for versioning
* **Monitoring**: Prometheus metrics and Grafana dashboards
* **Modular Design**: NVIDIA Morpheus-compatible architecture

Quick Links
-----------

* :doc:`getting_started` - Installation and setup
* :doc:`architecture` - System architecture and design
* :doc:`api/index` - Complete API reference
* :doc:`examples` - Usage examples and tutorials
* :doc:`configuration` - Configuration reference

Key Features
------------

DFP Behavioral Learning
~~~~~~~~~~~~~~~~~~~~~~~

The platform uses AutoEncoder neural networks to learn normal user behavior patterns:

* Training on historical user activity (60-day windows)
* Per-user models for personalized anomaly detection
* Automatic model versioning and registration
* Generic fallback models for new users

Geographic Features
~~~~~~~~~~~~~~~~~~~

Enhanced detection with location-aware features:

* Travel velocity calculations (km/h)
* Distance between consecutive events
* Impossible travel detection
* Location change patterns

FilterDetections
~~~~~~~~~~~~~~~~

NVIDIA standard binary threshold filtering:

* Z-score based anomaly scoring (mean_abs_z)
* Configurable threshold (default: 2.0)
* Output only anomalies for efficiency
* Statistical tracking and logging

Architecture Highlights
-----------------------

**Training Pipeline**:
    DFP_PREPROC → Geographic Features → Rolling Window → Data Prep → DFP Training → MLflow

**Inference Pipeline**:
    Kafka Consumer → DFP Preprocessing → DFP Inference → FilterDetections → Output

**Module Structure**:
    * ``modules/preprocessing`` - Data preprocessing and feature engineering
    * ``modules/training`` - Model training and management
    * ``modules/inference`` - Real-time inference and filtering
    * ``modules/io`` - Input/output operations
    * ``modules/control`` - Control message handling
    * ``modules/utils`` - Utilities and helpers

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
