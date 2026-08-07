Utilities Module
================

The utilities module provides helper functions and common utilities.

Metrics Utils
-------------

.. automodule:: modules.utils.metrics_utils
   :members:
   :undoc-members:
   :show-inheritance:

Example: Track Pipeline Metrics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.utils.metrics_utils import PipelineMetrics, push_metrics_to_gateway

   # Initialize metrics
   metrics = PipelineMetrics(pipeline_name='training')

   # Record events
   metrics.record_events_processed(count=1000)
   metrics.record_batch_processed(count=1)

   # Time operations
   with metrics.time_operation('preprocessing'):
       # ... preprocessing code ...
       pass

   with metrics.time_operation('training'):
       # ... training code ...
       pass

   # Record throughput
   metrics.record_throughput(events_per_second=125.5)

   # Record errors
   metrics.record_errors(count=2)

   # Push to Pushgateway (for batch jobs)
   push_metrics_to_gateway(
       job='dfp_training',
       instance='batch_20250101_120000'
   )

MLflow Utils
------------

.. automodule:: modules.utils.mlflow_utils
   :members:
   :undoc-members:
   :show-inheritance:
