Configuration
=============

This document describes the configuration system and available options.

Configuration Files
-------------------

The platform uses YAML configuration with OmegaConf for hierarchical config management.

Main Configuration Files
~~~~~~~~~~~~~~~~~~~~~~~~

- ``config/base_config.yaml`` - Global project settings
- ``config/pipeline.yaml`` - Pipeline-specific configuration
- ``config/feature_schema.yaml`` - Feature engineering definitions
- ``config/mlflow.yaml`` - MLflow tracking and registry
- ``config/logging.yaml`` - Logging configuration

Configuration Structure
-----------------------

Base Configuration
~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   # config/base_config.yaml
   dfp:
     preprocessing:
       enable_geographic_features: true
       timestamp_column: "timestamp"
       userid_column: "username"
       
     training:
       min_history: 300
       min_increment: 300
       max_history: "60d"
       epochs: 30
       validation_size: 0.1
       seed: 42
       
     inference:
       detection_criteria:
         field_name: "mean_abs_z"
         threshold: 2.0
         filter_source: "DATAFRAME"

Pipeline Configuration
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   # config/pipeline.yaml
   source_schema:
     schema_str: "@source_schema@"
     encoding: "latin1"
     
   mlflow:
     tracking_uri: "http://localhost:5000"
     experiment_name: "dfp/training"
     model_name_template: "DFP-{user_id}"
     
   feature_columns:
     - appincrement
     - logcountincrement
     - locincrement
     - travel_speed_kmph

Feature Schema
~~~~~~~~~~~~~~

.. code-block:: yaml

   # config/feature_schema.yaml
   feature_sets:
     default:
       - name: appDisplayName
         dtype: str
         custom_preproc_func: null
         
       - name: location_geoCoordinates_latitude
         dtype: float64
         custom_preproc_func: null
         
       - name: travel_speed_kmph
         dtype: float64
         custom_preproc_func: null

Environment Variables
---------------------

Override configuration via environment variables:

.. code-block:: bash

   # MLflow settings
   export MLFLOW_TRACKING_URI="http://mlflow:5000"
   export MLFLOW_EXPERIMENT_NAME="dfp/production"
   
   # Training settings
   export DFP_EPOCHS=50
   export DFP_MAX_HISTORY="90d"
   
   # Inference settings
   export DFP_THRESHOLD=3.0
   export KAFKA_BOOTSTRAP_SERVERS="kafka:9092"

Variable Interpolation
----------------------

Use OmegaConf interpolation for dynamic values:

.. code-block:: yaml

   paths:
     data_dir: "/data"
     cache_dir: "${paths.data_dir}/cache"
     output_dir: "${paths.data_dir}/output"
   
   training:
     cache_dir: "${paths.cache_dir}"

Configuration in Code
---------------------

Loading Configuration
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from omegaconf import OmegaConf
   
   # Load config
   config = OmegaConf.load('config/pipeline.yaml')
   
   # Access values
   threshold = config.dfp.inference.detection_criteria.threshold
   
   # Merge configs
   base_config = OmegaConf.load('config/base_config.yaml')
   merged = OmegaConf.merge(base_config, config)

Validating Configuration
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   def validate_config(config):
       """Validate configuration has required fields."""
       required = [
           'dfp.training.epochs',
           'dfp.inference.detection_criteria.threshold',
           'mlflow.tracking_uri'
       ]
       
       for field in required:
           if OmegaConf.select(config, field) is None:
               raise ValueError(f"Missing required config: {field}")

Configuration Best Practices
-----------------------------

1. **Use defaults**: Provide sensible defaults in base config
2. **Environment-specific**: Override in pipeline config
3. **Type safety**: Use proper YAML types (int, float, bool)
4. **Documentation**: Comment complex settings
5. **Validation**: Validate config at startup
6. **Secrets**: Use environment variables for sensitive data

Example: Complete Configuration
--------------------------------

.. code-block:: python

   from omegaconf import OmegaConf
   import os
   
   # Load base configuration
   base_config = OmegaConf.load('config/base_config.yaml')
   pipeline_config = OmegaConf.load('config/pipeline.yaml')
   
   # Merge configurations
   config = OmegaConf.merge(base_config, pipeline_config)
   
   # Override from environment
   env_overrides = OmegaConf.create({
       'mlflow': {
           'tracking_uri': os.environ.get('MLFLOW_TRACKING_URI', config.mlflow.tracking_uri)
       },
       'dfp': {
           'training': {
               'epochs': int(os.environ.get('DFP_EPOCHS', config.dfp.training.epochs))
           },
           'inference': {
               'detection_criteria': {
                   'threshold': float(os.environ.get('DFP_THRESHOLD', 
                                                     config.dfp.inference.detection_criteria.threshold))
               }
           }
       }
   })
   
   config = OmegaConf.merge(config, env_overrides)
   
   # Validate
   validate_config(config)
   
   # Use in pipeline
   from pipelines.training_pipeline import DFPTrainingPipeline
   
   pipeline = DFPTrainingPipeline(
       config=config,
       cache_dir=config.paths.cache_dir,
       mlflow_manager=mlflow_manager,
       metrics=metrics
   )
