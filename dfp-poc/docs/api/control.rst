Control Module
==============

The control module provides control message handling for pipeline communication.

Control Message
---------------

.. automodule:: modules.control.control_message
   :members:
   :undoc-members:
   :show-inheritance:

Example: Create Control Message
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.control.control_message import ControlMessage
   import pandas as pd

   # Create message
   msg = ControlMessage()

   # Set metadata
   msg.set_metadata('user_id', 'alice')
   msg.set_metadata('model_version', 'v1.2.3')
   msg.set_metadata('timestamp', '2025-01-01T10:00:00Z')

   # Set payload
   df = pd.DataFrame({
       'feature1': [1, 2, 3],
       'feature2': [10, 20, 30]
   })
   msg.payload(df)

   # Add tasks
   msg.add_task('training', {
       'type': 'training',
       'properties': {'epochs': 30}
   })

   # Read metadata
   user_id = msg.get_metadata('user_id')
   model_version = msg.get_metadata('model_version', default='unknown')

   # Check metadata
   if msg.has_metadata('timestamp'):
       print("Timestamp is set")

   # Get payload
   data = msg.payload()
   print(f"Payload shape: {data.shape}")

Example: Pass Through Pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.control.control_message import ControlMessage
   from modules.preprocessing.dfp_preprocessing import DFPPreprocessing
   from modules.training.dfp_trainer import DFPTrainer

   # Create initial message
   msg = ControlMessage()
   msg.set_metadata('user_id', 'alice')
   msg.payload(raw_data)

   # Pass through preprocessing
   preprocessor = DFPPreprocessing(config)
   preprocessed_data = preprocessor.preprocess(msg.payload())
   msg.payload(preprocessed_data)

   # Add training task
   msg.add_task('training', {'type': 'training', 'properties': {}})

   # Pass to trainer
   trainer = DFPTrainer(config)
   result = trainer.train(msg)

   # Access results
   if result:
       trained_model = result.get_metadata('trained_model')
       train_loss = result.get_metadata('train_loss')
       print(f"Training complete: loss={train_loss:.4f}")
