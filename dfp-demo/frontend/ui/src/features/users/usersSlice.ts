import { USERS_INITIAL_STATE } from '@/constants';
import type { User } from '@/types';
import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

const usersSlice = createSlice({
  name: 'users',
  initialState: USERS_INITIAL_STATE,
  reducers: {
    setUsers: (state, action: PayloadAction<User[]>) => {
      state.items = action.payload;
    },
    updateUser: (state, action: PayloadAction<User>) => {
      const index = state.items.findIndex((u) => u.username === action.payload.username);
      if (index !== -1) {
        state.items[index] = action.payload;
      } else {
        state.items.push(action.payload);
      }
    },
    selectUser: (state, action: PayloadAction<User | null>) => {
      state.selectedUser = action.payload;
    },
    setSearchQuery: (state, action: PayloadAction<string>) => {
      state.searchQuery = action.payload;
    },
  },
});

export const { setUsers, updateUser, selectUser, setSearchQuery } = usersSlice.actions;

export default usersSlice.reducer;
