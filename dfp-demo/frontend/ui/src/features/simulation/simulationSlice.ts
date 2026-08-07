import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

interface SimulationState {
  running: boolean;
}

const simulationSlice = createSlice({
  name: 'simulation',
  initialState: { running: false } as SimulationState,
  reducers: {
    setSimulationRunning: (state, action: PayloadAction<boolean>) => {
      state.running = action.payload;
    },
  },
});

export const { setSimulationRunning } = simulationSlice.actions;
export default simulationSlice.reducer;
