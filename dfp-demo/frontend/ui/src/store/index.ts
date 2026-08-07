import { configureStore } from '@reduxjs/toolkit';
import anomaliesReducer from '../features/anomalies/anomaliesSlice';
import usersReducer from '../features/users/usersSlice';
import simulationReducer from '../features/simulation/simulationSlice';

export const store = configureStore({
  reducer: {
    anomalies: anomaliesReducer,
    users: usersReducer,
    simulation: simulationReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        // Ignore these action types
        ignoredActions: ['anomalies/addAnomaly'],
      },
    }),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
