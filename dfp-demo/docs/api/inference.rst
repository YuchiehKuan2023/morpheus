Inference Module
================

The inference module provides real-time inference and anomaly detection functionality.

DFP Inference
-------------

.. automodule:: modules.inference.dfp_inference
   :members:
   :undoc-members:
   :show-inheritance:

Example: Run Inference
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.inference.dfp_inference import DFPInference
   from modules.control.control_message import ControlMessage
   import pandas as pd

   # Initialize inference
   inference = DFPInference(
       config={
           'model_name_template': 'DFP-{user_id}',
           'fallback_model_name': 'DFP-generic'
       },
       mlflow_manager=mlflow_manager
   )

   # Prepare input data
   df = pd.DataFrame({
       'feature1': [10, 20, 30],
       'feature2': [100, 200, 300],
       'feature3': [1000, 2000, 3000]
   })

   # Create control message
   msg = ControlMessage()
   msg.set_metadata('user_id', 'alice')
   msg.payload(df)

   # Run inference
   result = inference.infer(msg)

   # Access results
   if result:
       results_df = result.payload()
       print(results_df[['mean_abs_z', 'feature1_z_loss']])

Filter Detections
-----------------

.. automodule:: modules.inference.filter_detections
   :members:
   :undoc-members:
   :show-inheritance:

Example: Filter Anomalies
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.inference.filter_detections import FilterDetections
   from modules.control.control_message import ControlMessage
   import pandas as pd

   # Initialize filter
   filter_module = FilterDetections({
       'detection_criteria': {
           'field_name': 'mean_abs_z',
           'threshold': 2.0,
           'filter_source': 'DATAFRAME'
       },
       'output': {
           'copy_data': True
       }
   })

   # Prepare inference results
   df = pd.DataFrame({
       'mean_abs_z': [0.5, 1.2, 3.5, 0.8, 4.2],  # 3.5 and 4.2 are anomalies
       'feature1_z_loss': [0.3, 0.8, 2.1, 0.5, 3.0],
       'timestamp': pd.date_range('2025-01-01', periods=5, freq='1H')
   })

   # Create control message
   msg = ControlMessage()
   msg.set_metadata('user_id', 'alice')
   msg.payload(df)

   # Filter anomalies
   result = filter_module.filter(msg)

   # Access filtered anomalies
   if result:
       anomalies = result.payload()
       print(f"Found {len(anomalies)} anomalies")
       print(anomalies[['timestamp', 'mean_abs_z']])
   else:
       print("No anomalies detected")

   # Get statistics
   stats = filter_module.get_statistics()
   print(f"Anomaly rate: {stats['anomaly_rate']:.2f}%")

Standalone Function
~~~~~~~~~~~~~~~~~~~

For simple use cases without ControlMessage wrapper:

.. code-block:: python

   from modules.inference.filter_detections import filter_detections
   import pandas as pd

   # Prepare data
   df = pd.DataFrame({
       'mean_abs_z': [0.5, 1.2, 3.5, 0.8, 4.2],
       'feature1': [10, 20, 30, 40, 50]
   })

   # Filter anomalies (returns only rows above threshold)
   anomalies = filter_detections(
       df,
       field_name='mean_abs_z',
       threshold=2.0,
       include_all=False
   )

   print(f"Anomalies: {len(anomalies)}/{len(df)} rows")

   # Or include all with flag
   all_with_flags = filter_detections(
       df,
       field_name='mean_abs_z',
       threshold=2.0,
       include_all=True
   )
   print(all_with_flags[['mean_abs_z', 'is_anomaly']])
