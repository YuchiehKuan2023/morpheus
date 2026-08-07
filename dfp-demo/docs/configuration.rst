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

   # Agentic conversational AI settings
   export CHAT_MODE="agentic"          # "pipeline" or "agentic"
   export LLM_PROVIDER_URL="https://models.inference.ai.azure.com"
   export LLM_API_KEY="your-github-models-api-key"

Agentic Conversational AI
--------------------------

The platform includes a ReAct-based agentic conversational AI
that can autonomously reason, plan, and call tools to answer security
analysis questions.

Chat Mode
~~~~~~~~~

Set via ``CHAT_MODE`` environment variable or ``config/base_config.yaml``:

- ``pipeline`` — Legacy 3-pass pipeline (intent → route → answer)
- ``agentic`` — ReAct agent loop with planning, reflection, and memory

.. code-block:: yaml

   # config/base_config.yaml
   agentic:
     chat_mode: "agentic"

Agent Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   agentic:
     # ReAct loop limits
     max_iterations: 8          # Maximum reasoning steps per query
     max_tool_calls: 15         # Total tool executions per query
     max_observation_tokens: 12000  # Cumulative observation budget (tokens)

     # Tools blocked in agentic mode (safety)
     blocked_tools:
       - "query_database"       # Prevent raw SQL execution

     # LLM models (via GitHub Models endpoint)
     router_model: "gpt-4o-mini"        # Cheap model for reasoning steps
     answer_model: "Llama-3.3-70B-Instruct"  # Expensive model for final answer

     # Tool result caching TTLs (seconds, 0 = disabled)
     cache:
       default_ttl: 30
       user_profile_ttl: 60
       baseline_ttl: 120
       risk_summary_ttl: 30

     # Server-Sent Events streaming for real-time trace display
     enable_streaming: true

Guard Rails
~~~~~~~~~~~

The agent has built-in safety limits to prevent runaway execution:

- **Iteration budget**: Maximum reasoning steps (default 8)
- **Tool-call budget**: Maximum tool executions (default 15)
- **Token budget**: Cumulative observation size limit (default 12,000)
- **Blocked tools**: Certain tools (e.g. ``query_database``) are blocked
- **Duplicate detection**: Exact-duplicate tool calls are blocked

Available Tools
~~~~~~~~~~~~~~~

The agentic system has access to 14 tools across multiple data sources:

- **PostgreSQL**: ``search_anomalies``, ``get_anomaly_detail``, ``get_user_profile``,
  ``get_risk_summary``, ``get_top_anomalies``, ``get_anomaly_timeline``,
  ``get_root_cause_summary``, ``get_dimension_ranking``, ``get_user_behaviour_baseline``
- **Qdrant**: ``semantic_search_anomalies`` (dense vector similarity)
- **Neo4j**: ``get_neo4j_graph`` (knowledge graph relationships)
- **LLM**: ``get_investigation``, ``get_llm_explanations``
- **Hybrid**: ``hybrid_search`` (dense + sparse + graph + structured)

API Endpoints
~~~~~~~~~~~~~

- ``POST /api/v1/chat/query`` — Standard query (returns full response)
- ``POST /api/v1/chat/query/stream`` — SSE streaming (real-time reasoning trace)
- ``GET /api/v1/chat/agent-metrics`` — Aggregate agent performance statistics

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
