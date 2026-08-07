I/O Module
==========

The I/O module provides input/output operations for data loading and streaming.

File to DataFrame
-----------------

.. automodule:: modules.io.file_to_df
   :members:
   :undoc-members:
   :show-inheritance:

Example: Load Files
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.io.file_to_df import FileToDataFrame
   from modules.preprocessing.source_schema import build_azure_source_schema

   # Initialize loader
   loader = FileToDataFrame({
       'source_schema': build_azure_source_schema(),
       'filter_null': True,
       'timestamp_column_name': 'timestamp'
   })

   # Load single file
   df = loader.load_files(['data/input/events.json'])
   print(f"Loaded {len(df)} records")

   # Load multiple files
   files = [
       'data/input/events_2025_01.json',
       'data/input/events_2025_02.json'
   ]
   df = loader.load_files(files)

Kafka Consumer
--------------

.. automodule:: modules.io.kafka_consumer
   :members:
   :undoc-members:
   :show-inheritance:

Example: Consume from Kafka
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.io.kafka_consumer import KafkaDataSource

   # Initialize consumer
   consumer = KafkaDataSource({
       'bootstrap_servers': 'localhost:9092',
       'topic': 'dfp-events',
       'group_id': 'dfp-inference',
       'auto_offset_reset': 'latest',
       'max_batch_size': 1024
   })

   # Start consuming
   consumer.start()

   try:
       # Get batches of messages
       while True:
           batch = consumer.get_batch(max_messages=100, timeout=1.0)
           if batch:
               print(f"Received {len(batch)} messages")
               # Process batch...
   finally:
       consumer.stop()

Kafka Producer
--------------

.. automodule:: modules.io.kafka_producer
   :members:
   :undoc-members:
   :show-inheritance:

Example: Produce to Kafka
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.io.kafka_producer import KafkaDataSink
   import pandas as pd

   # Initialize producer
   producer = KafkaDataSink({
       'bootstrap_servers': 'localhost:9092',
       'topic': 'dfp-detections',
       'compression_type': 'gzip'
   })

   # Send data
   df = pd.DataFrame({
       'user_id': ['alice'],
       'timestamp': ['2025-01-01T10:00:00Z'],
       'mean_abs_z': [3.5],
       'anomaly_source': ['dfp']
   })

   producer.write(df)
   producer.flush()
