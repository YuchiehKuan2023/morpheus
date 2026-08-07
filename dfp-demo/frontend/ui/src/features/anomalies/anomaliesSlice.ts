import { ANOMALIES_INITIAL_STATE } from '@/constants';
import type { Anomaly } from '@/types';
import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

const anomaliesSlice = createSlice({
  name: 'anomalies',
  initialState: ANOMALIES_INITIAL_STATE,
  reducers: {
    addAnomaly: (state, action: PayloadAction<Anomaly>) => {
      state.items.unshift(action.payload);
    },
    updateAnomaly: (state, action: PayloadAction<Anomaly>) => {
      const index = state.items.findIndex((a) => a.id === action.payload.id);
      if (index !== -1) {
        state.items[index] = action.payload;
      }
    },
    setAnomalies: (state, action: PayloadAction<Anomaly[]>) => {
      state.items = action.payload;
    },
    setSeverityFilter: (state, action: PayloadAction<string[]>) => {
      state.filter.severity = action.payload;
    },
    setStatusFilter: (state, action: PayloadAction<string[]>) => {
      state.filter.status = action.payload;
    },
    setSearchQuery: (state, action: PayloadAction<string>) => {
      state.filter.searchQuery = action.payload;
    },
    selectAnomaly: (state, action: PayloadAction<Anomaly | null>) => {
      state.selectedAnomaly = action.payload;
    },
  },
});

export const {
  addAnomaly,
  updateAnomaly,
  setAnomalies,
  setSeverityFilter,
  setStatusFilter,
  setSearchQuery,
  selectAnomaly,
} = anomaliesSlice.actions;

export default anomaliesSlice.reducer;
