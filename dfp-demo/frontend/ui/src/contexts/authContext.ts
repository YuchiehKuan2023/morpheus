import { createContext } from 'react';

export interface AuthContextValue {
  user: import('@/types').AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

/** Stable context reference — kept in a non-component file so HMR never recreates it. */
export const AuthContext = createContext<AuthContextValue | null>(null);
