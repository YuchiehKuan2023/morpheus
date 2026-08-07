Preprocessing Module
====================

The preprocessing module provides data preprocessing and feature engineering functionality.

.. automodule:: modules.preprocessing.dfp_preprocessing
   :members:
   :undoc-members:
   :show-inheritance:

Geographic Features
-------------------

.. automodule:: modules.preprocessing.geographic_features
   :members:
   :undoc-members:
   :show-inheritance:

Example: Calculate Travel Features
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.preprocessing.geographic_features import calculate_travel_features
   import pandas as pd

   # Sample data with coordinates
   df = pd.DataFrame({
       'username': ['alice'] * 3,
       'timestamp': pd.date_range('2025-01-01', periods=3, freq='1H'),
       'location_geoCoordinates_latitude': [40.7128, 40.7580, 40.7614],
       'location_geoCoordinates_longitude': [-74.0060, -73.9855, -73.9776]
   })

   # Calculate travel features
   df_with_features = calculate_travel_features(
       df,
       user_col='username',
       timestamp_col='timestamp'
   )

   print(df_with_features[['travel_speed_kmph', 'distance_km']])

Rolling Window
--------------

.. automodule:: modules.preprocessing.rolling_window
   :members:
   :undoc-members:
   :show-inheritance:

Example: Build Rolling Window
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.preprocessing.rolling_window import RollingWindow
   import pandas as pd

   # Initialize rolling window
   window = RollingWindow(
       cache_dir='data/cache',
       timestamp_column='timestamp',
       cache_mode='aggregate',
       min_history=300,
       max_history='60d'
   )

   # Build window for user
   df = pd.DataFrame({
       'timestamp': pd.date_range('2025-01-01', periods=1000, freq='1H'),
       'feature1': range(1000),
       'feature2': range(1000, 2000)
   })

   windowed_df = window.build_window(user_id='alice', incoming_df=df)

Data Preparation
----------------

.. automodule:: modules.preprocessing.data_prep
   :members:
   :undoc-members:
   :show-inheritance:

User Splitting
--------------

.. automodule:: modules.preprocessing.user_splitting
   :members:
   :undoc-members:
   :show-inheritance:

Example: Split Users
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from modules.preprocessing.user_splitting import UserSplitter
   import pandas as pd

   # Initialize splitter
   splitter = UserSplitter(
       userid_column='username',
       include_generic=False,
       include_individual=True
   )

   # Split data by user
   df = pd.DataFrame({
       'username': ['alice', 'alice', 'bob', 'bob'],
       'feature1': [1, 2, 3, 4],
       'timestamp': pd.date_range('2025-01-01', periods=4, freq='1H')
   })

   user_dfs = splitter.split_users(df)
   # Returns: {'alice': DataFrame, 'bob': DataFrame}
