Deployment
==========

This document provides deployment instructions for production environments.

Prerequisites
-------------

System Requirements
~~~~~~~~~~~~~~~~~~~

- **CPU**: 8+ cores recommended
- **RAM**: 16GB+ (32GB for large datasets)
- **GPU**: NVIDIA GPU with CUDA 11.8+ (optional, for acceleration)
- **Disk**: 100GB+ SSD for cache and models
- **Network**: 1Gbps+ for Kafka streaming

Software Requirements
~~~~~~~~~~~~~~~~~~~~~

- Python 3.10 - 3.12
- Docker 20.10+
- Docker Compose 2.0+
- CUDA Toolkit 11.8+ (for GPU support)

Installation
------------

1. Clone Repository
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/Deloitte-UK-Innersource/morpheus-dfp.git
   cd morpheus-dfp/dfp-poc

2. Create Virtual Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate

3. Install Dependencies
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   pip install --upgrade pip
   pip install -e .
   
   # Optional: Install dev dependencies
   pip install -e ".[dev]"
   
   # Optional: Install visualization tools
   pip install -e ".[viz]"

4. Configure Environment
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Copy example environment file
   cp .env.example .env
   
   # Edit configuration
   nano .env

Example ``.env`` file:

.. code-block:: bash

   # MLflow
   MLFLOW_TRACKING_URI=http://localhost:5000
   
   # Kafka
   KAFKA_BOOTSTRAP_SERVERS=localhost:9092
   KAFKA_INPUT_TOPIC=dfp-events
   KAFKA_OUTPUT_TOPIC=dfp-detections
   
   # Training
   DFP_EPOCHS=30
   DFP_MAX_HISTORY=60d
   
   # Inference
   DFP_THRESHOLD=2.0

Service Deployment
------------------

Start Services
~~~~~~~~~~~~~~

.. code-block:: bash

   cd services
   ./start_services.sh

This starts:

- Kafka (KRaft mode, port 9092)
- MLflow (port 5000)
- Prometheus (port 9090)
- Grafana (port 3000)

Verify services:

.. code-block:: bash

   ./check_services.sh

Training Pipeline
-----------------

Initial Training
~~~~~~~~~~~~~~~~

.. code-block:: bash

   python pipelines/training_pipeline.py \\
       --config config/pipeline.yaml \\
       --data data/input/historical_data.json

Scheduled Training
~~~~~~~~~~~~~~~~~~

Use cron for periodic retraining:

.. code-block:: bash

   # Edit crontab
   crontab -e
   
   # Add daily training at 2 AM
   0 2 * * * cd /path/to/dfp-poc && /path/to/.venv/bin/python pipelines/training_pipeline.py --config config/pipeline.yaml --data data/input/daily_data.json

Inference Pipeline
------------------

As a Service
~~~~~~~~~~~~

Run inference as a long-running service:

.. code-block:: bash

   python pipelines/inference_pipeline.py \\
       --config config/pipeline.yaml \\
       --mode service

With Docker
~~~~~~~~~~~

.. code-block:: dockerfile

   FROM python:3.11-slim
   
   WORKDIR /app
   COPY . /app
   
   RUN pip install --no-cache-dir -e .
   
   CMD ["python", "pipelines/inference_pipeline.py", "--config", "config/pipeline.yaml"]

Build and run:

.. code-block:: bash

   docker build -t dfp-inference .
   docker run -d --name dfp-inference \\
       --network host \\
       -v $(pwd)/config:/app/config \\
       -v $(pwd)/data:/app/data \\
       dfp-inference

Monitoring
----------

Access Dashboards
~~~~~~~~~~~~~~~~~

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **MLflow**: http://localhost:5000

Import Grafana Dashboard
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Dashboard JSON is at config/grafana_dashboard.json
   # Import via Grafana UI: Dashboards → Import → Upload JSON

Metrics Endpoints
~~~~~~~~~~~~~~~~~

Inference pipeline exposes Prometheus metrics:

.. code-block:: text

   http://localhost:8000/metrics

Key metrics:

- ``dfp_events_processed_total``
- ``dfp_anomalies_detected_total``
- ``dfp_processing_duration_seconds``
- ``dfp_model_load_duration_seconds``

Production Considerations
-------------------------

High Availability
~~~~~~~~~~~~~~~~~

1. **Kafka**: Deploy multi-broker cluster
2. **MLflow**: Use external database (PostgreSQL)
3. **Inference**: Run multiple instances behind load balancer
4. **Monitoring**: Deploy Prometheus with alerting

.. code-block:: yaml

   # docker-compose.prod.yaml
   services:
     kafka1:
       image: confluentinc/cp-kafka:latest
       # ... kafka config
     
     kafka2:
       image: confluentinc/cp-kafka:latest
       # ... kafka config
     
     inference1:
       image: dfp-inference:latest
       # ... instance 1
     
     inference2:
       image: dfp-inference:latest
       # ... instance 2

Security
~~~~~~~~

1. **Kafka**: Enable SASL/SSL authentication
2. **MLflow**: Use authentication plugin
3. **Secrets**: Use environment variables or secret managers
4. **Network**: Isolate services on private network

.. code-block:: bash

   # Use Azure Key Vault for secrets
   export MLFLOW_TRACKING_URI=$(az keyvault secret show --name mlflow-uri --vault-name my-vault --query value -o tsv)

Performance Tuning
~~~~~~~~~~~~~~~~~~

1. **Batch size**: Increase for higher throughput
2. **GPU**: Enable CUDA for preprocessing
3. **Cache**: Use SSD for rolling window cache
4. **Parallelism**: Multiple Kafka consumer threads

.. code-block:: yaml

   # config/pipeline.yaml
   inference:
     batch_size: 1024
     num_workers: 4
     use_gpu: true

Backup and Recovery
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Backup MLflow artifacts
   rsync -avz data/mlflow/ backup/mlflow/
   
   # Backup cache
   rsync -avz data/cache/ backup/cache/
   
   # Backup configurations
   rsync -avz config/ backup/config/

Troubleshooting
---------------

Common Issues
~~~~~~~~~~~~~

**Issue**: Models not loading

.. code-block:: bash

   # Check MLflow connection
   curl http://localhost:5000/api/2.0/mlflow/experiments/list
   
   # Verify model exists
   mlflow models list --name DFP-alice

**Issue**: Kafka connection errors

.. code-block:: bash

   # Check Kafka is running
   docker ps | grep kafka
   
   # Test connection
   kafka-console-consumer --bootstrap-server localhost:9092 --topic dfp-events --from-beginning

**Issue**: High memory usage

.. code-block:: bash

   # Reduce batch size
   export DFP_BATCH_SIZE=512
   
   # Reduce cache size
   export DFP_MAX_HISTORY=30d

Logs
~~~~

.. code-block:: bash

   # Pipeline logs
   tail -f logs/inference.log
   
   # Service logs
   docker-compose logs -f kafka mlflow
   
   # System metrics
   docker stats

Support
-------

For deployment support:

- GitHub Issues: https://github.com/Deloitte-UK-Innersource/morpheus-dfp/issues
- Documentation: :doc:`index`
- Examples: :doc:`examples`
