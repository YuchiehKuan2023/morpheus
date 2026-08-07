Getting Started
===============

This guide will help you get started with the Morpheus DFP platform.

Installation
------------

Prerequisites
~~~~~~~~~~~~~

* Python 3.10 - 3.12
* CUDA 11.8+ (optional, for GPU acceleration)
* Docker and Docker Compose (for services)
* 8GB+ RAM recommended

Install from Source
~~~~~~~~~~~~~~~~~~~

1. Clone the repository:

.. code-block:: bash

   git clone https://github.com/Deloitte-UK-Innersource/morpheus-dfp.git
   cd morpheus-dfp/dfp-poc

2. Create virtual environment:

.. code-block:: bash

   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate

3. Install dependencies:

.. code-block:: bash

   pip install -e .

4. Install development dependencies (optional):

.. code-block:: bash

   pip install -e ".[dev]"

Quick Start
-----------

1. Start Services
~~~~~~~~~~~~~~~~~

Start required services (Kafka, MLflow, Prometheus, Grafana):

.. code-block:: bash

   cd services
   ./start_services.sh

2. Train Models
~~~~~~~~~~~~~~~

Train initial user models:

.. code-block:: bash

   python pipelines/training_pipeline.py \\
       --config config/pipeline.yaml \\
       --data data/input/training_data.json

3. Run Inference
~~~~~~~~~~~~~~~~

Start real-time inference:

.. code-block:: bash

   python pipelines/inference_pipeline.py \\
       --config config/pipeline.yaml

4. Monitor
~~~~~~~~~~

Access monitoring dashboards:

* Grafana: http://localhost:3000 (admin/admin)
* Prometheus: http://localhost:9090
* MLflow: http://localhost:5000

Configuration
-------------

The platform uses YAML configuration files:

* ``config/base_config.yaml`` - Global settings
* ``config/pipeline.yaml`` - Pipeline configuration
* ``config/feature_schema.yaml`` - Feature definitions
* ``config/mlflow.yaml`` - MLflow settings

Example configuration:

.. code-block:: yaml

   dfp:
     preprocessing:
       enable_geographic_features: true
       
     training:
       min_history: 300
       max_history: "60d"
       epochs: 30
       
     inference:
       detection_criteria:
         threshold: 2.0
         field_name: "mean_abs_z"

Next Steps
----------

* Read the :doc:`architecture` documentation
* Explore the :doc:`api/index` reference
* Check out :doc:`examples` for common use cases
* Review :doc:`configuration` for detailed settings
