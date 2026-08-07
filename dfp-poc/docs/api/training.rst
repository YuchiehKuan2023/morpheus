Training Module
===============

The training module provides model training and management functionality.

DFP Trainer
-----------

.. automodule:: modules.training.dfp_trainer
   :members:
   :undoc-members:
   :show-inheritance:

Example: Train Model
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.training.dfp_trainer import DFPTrainer
   from modules.control.control_message import ControlMessage
   import pandas as pd

   # Initialize trainer
   trainer = DFPTrainer({
       'model': {
           'encoder_layers': [512, 500],
           'decoder_layers': [512],
           'activation': 'relu',
           'learning_rate': 0.01,
           'feature_columns': ['feature1', 'feature2', 'feature3']
       },
       'training': {
           'epochs': 30,
           'validation_size': 0.1,
           'min_training_samples': 100
       }
   })

   # Prepare training data
   df = pd.DataFrame({
       'feature1': range(500),
       'feature2': range(500, 1000),
       'feature3': range(1000, 1500)
   })

   # Create control message
   msg = ControlMessage()
   msg.set_metadata('user_id', 'alice')
   msg.payload(df)
   msg.add_task('training', {'type': 'training', 'properties': {}})

   # Train model
   result = trainer.train(msg)

   # Access trained model
   if result:
       model = result.get_metadata('trained_model')
       print(f"Model trained with {result.get_metadata('train_size')} samples")

MLflow Model Writer
-------------------

.. automodule:: modules.training.mlflow_model_writer
   :members:
   :undoc-members:
   :show-inheritance:

Example: Save Model to MLflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.training.mlflow_model_writer import MLflowModelWriter
   from modules.control.control_message import ControlMessage

   # Initialize writer
   writer = MLflowModelWriter({
       'mlflow': {
           'tracking_uri': 'http://localhost:5000',
           'model_name_template': 'DFP-{user_id}',
           'experiment_name': 'dfp/training',
           'register_model': True
       }
   })

   # Assume we have a trained model in a control message
   msg = ControlMessage()
   msg.set_metadata('user_id', 'alice')
   msg.set_metadata('trained_model', model)  # PyTorch model
   msg.set_metadata('train_loss', 0.05)
   msg.set_metadata('val_loss', 0.06)

   # Save to MLflow
   writer.write_model(msg)
   # Model registered as "DFP-alice" in MLflow
