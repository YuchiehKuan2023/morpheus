Examples
========

This section provides practical examples for common use cases.

Training Pipeline Example
-------------------------

Complete example of training user models:

.. code-block:: python

   from pathlib import Path
   from modules.io.file_to_df import FileToDataFrame
   from modules.preprocessing.user_splitting import UserSplitter
   from modules.preprocessing.geographic_features import calculate_travel_features
   from modules.preprocessing.rolling_window import RollingWindow
   from modules.preprocessing.dfp_preprocessing import DFPPreprocessing
   from modules.training.dfp_trainer import DFPTrainer
   from modules.training.mlflow_model_writer import MLflowModelWriter
   from modules.utils.mlflow_manager import MLflowManager
   from modules.control.control_message import ControlMessage

   # Initialize components
   file_loader = FileToDataFrame({
       'source_schema': build_azure_source_schema(),
       'filter_null': True
   })

   user_splitter = UserSplitter(userid_column='username')

   rolling_window = RollingWindow(
       cache_dir='data/cache',
       cache_mode='aggregate',
       max_history='60d'
   )

   preprocessor = DFPPreprocessing({
       'schema_file': 'config/feature_schema.yaml'
   })

   trainer = DFPTrainer({
       'model': {'encoder_layers': [512, 500]},
       'training': {'epochs': 30}
   })

   mlflow_manager = MLflowManager({
       'tracking_uri': 'http://localhost:5000'
   })

   model_writer = MLflowModelWriter({
       'mlflow': {'model_name_template': 'DFP-{user_id}'}
   })

   # Load data
   df = file_loader.load_files(['data/input/training_data.json'])

   # Split by user
   user_dfs = user_splitter.split_users(df)

   # Process each user
   for user_id, user_df in user_dfs.items():
       # Calculate geographic features
       user_df = calculate_travel_features(user_df)
       
       # Build rolling window
       windowed_df = rolling_window.build_window(user_id, user_df)
       
       # Preprocess
       preprocessed_df = preprocessor.preprocess(windowed_df)
       
       # Train
       msg = ControlMessage()
       msg.set_metadata('user_id', user_id)
       msg.payload(preprocessed_df)
       msg.add_task('training', {'type': 'training'})
       
       result = trainer.train(msg)
       
       # Save model
       if result:
           model_writer.write_model(result)
           print(f"✓ {user_id}: model trained and saved")

Inference Pipeline Example
---------------------------

Complete example of real-time inference:

.. code-block:: python

   from modules.io.kafka_consumer import KafkaDataSource
   from modules.preprocessing.dfp_preprocessing import DFPPreprocessing
   from modules.preprocessing.geographic_features import calculate_travel_features
   from modules.inference.dfp_inference import DFPInference
   from modules.inference.filter_detections import FilterDetections
   from modules.io.kafka_producer import KafkaDataSink
   from modules.control.control_message import ControlMessage

   # Initialize components
   consumer = KafkaDataSource({
       'bootstrap_servers': 'localhost:9092',
       'topic': 'dfp-events',
       'group_id': 'dfp-inference'
   })

   preprocessor = DFPPreprocessing({
       'schema_file': 'config/feature_schema.yaml'
   })

   inference = DFPInference(
       config={'model_name_template': 'DFP-{user_id}'},
       mlflow_manager=mlflow_manager
   )

   filter_detections = FilterDetections({
       'detection_criteria': {
           'threshold': 2.0,
           'field_name': 'mean_abs_z'
       }
   })

   producer = KafkaDataSink({
       'bootstrap_servers': 'localhost:9092',
       'topic': 'dfp-detections'
   })

   # Start consuming
   consumer.start()

   try:
       while True:
           # Get batch
           batch = consumer.get_batch(max_messages=100, timeout=1.0)
           if not batch:
               continue
           
           # Convert to DataFrame
           df = pd.DataFrame(batch)
           
           # Group by user
           for user_id, user_df in df.groupby('username'):
               # Calculate features
               user_df = calculate_travel_features(user_df)
               
               # Preprocess
               preprocessed_df = preprocessor.preprocess(user_df)
               
               # Create message
               msg = ControlMessage()
               msg.set_metadata('user_id', user_id)
               msg.payload(preprocessed_df)
               
               # Run inference
               result = inference.infer(msg)
               
               # Filter anomalies
               if result:
                   anomalies = filter_detections.filter(result)
                   
                   # Output anomalies
                   if anomalies:
                       producer.write(anomalies.payload())
                       print(f"Detected {len(anomalies.payload())} anomalies for {user_id}")
           
           producer.flush()
   
   finally:
       consumer.stop()

Geographic Features Example
----------------------------

Calculate and analyze travel patterns:

.. code-block:: python

   from modules.preprocessing.geographic_features import (
       calculate_travel_features,
       detect_impossible_travel
   )
   import pandas as pd

   # Sample data
   df = pd.DataFrame({
       'username': ['alice'] * 5,
       'timestamp': pd.date_range('2025-01-01 10:00', periods=5, freq='1H'),
       'location_geoCoordinates_latitude': [40.7128, 40.7580, 51.5074, 40.7614, 40.7489],
       'location_geoCoordinates_longitude': [-74.0060, -73.9855, -0.1278, -73.9776, -73.9680]
   })

   # Calculate travel features
   df = calculate_travel_features(df, user_col='username', timestamp_col='timestamp')

   # Display results
   print(df[['timestamp', 'distance_km', 'ts_delta_hour', 'travel_speed_kmph']])

   # Detect impossible travel
   impossible_travel_df = detect_impossible_travel(
       df,
       speed_threshold_kmph=1000.0,
       user_col='username'
   )

   if not impossible_travel_df.empty:
       print(f"\nFound {len(impossible_travel_df)} impossible travel events:")
       print(impossible_travel_df[['timestamp', 'travel_speed_kmph']])

Custom Monitoring Example
--------------------------

Add custom metrics to your pipeline:

.. code-block:: python

   from modules.utils.metrics_utils import PipelineMetrics
   from prometheus_client import Gauge, Counter, Histogram
   import time

   # Initialize metrics
   metrics = PipelineMetrics(pipeline_name='custom')

   # Create custom metrics
   custom_gauge = Gauge(
       'dfp_custom_value',
       'Custom value metric',
       ['user_id']
   )

   custom_counter = Counter(
       'dfp_custom_events_total',
       'Total custom events',
       ['event_type']
   )

   custom_histogram = Histogram(
       'dfp_custom_processing_duration_seconds',
       'Custom processing duration',
       buckets=[0.1, 0.5, 1.0, 2.0, 5.0]
   )

   # Use in pipeline
   for user_id, user_data in process_users():
       start_time = time.time()
       
       # Process data
       result = process_user_data(user_data)
       
       # Record metrics
       custom_gauge.labels(user_id=user_id).set(result['score'])
       custom_counter.labels(event_type=result['type']).inc()
       
       duration = time.time() - start_time
       custom_histogram.observe(duration)
       
       metrics.record_events_processed(count=len(user_data))

Configuration Loading Example
------------------------------

Load and validate configuration:

.. code-block:: python

   from omegaconf import OmegaConf
   from pathlib import Path

   # Load base config
   base_config = OmegaConf.load('config/base_config.yaml')

   # Load pipeline config
   pipeline_config = OmegaConf.load('config/pipeline.yaml')

   # Merge configurations
   config = OmegaConf.merge(base_config, pipeline_config)

   # Access with dot notation
   epochs = config.dfp.training.epochs
   threshold = config.dfp.inference.detection_criteria.threshold

   # Validate required fields
   required_fields = [
       'dfp.preprocessing.enable_geographic_features',
       'dfp.training.max_history',
       'dfp.inference.detection_criteria.threshold'
   ]

   for field in required_fields:
       if OmegaConf.select(config, field) is None:
           raise ValueError(f"Required field missing: {field}")

   # Override from environment
   config = OmegaConf.merge(
       config,
       OmegaConf.create({
           'dfp': {
               'training': {
                   'epochs': int(os.environ.get('DFP_EPOCHS', epochs))
               }
           }
       })
   )

   print(OmegaConf.to_yaml(config))
