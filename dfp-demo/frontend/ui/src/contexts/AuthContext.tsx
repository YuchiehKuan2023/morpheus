import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { API } from '@/constants';
import type { AuthUser, LoginResponse, MeResponse } from '@/types';
import { AuthContext, type AuthContextValue } from './authContext';

/** How often (ms) we probe /auth/me to detect expired sessions. */
const AUTH_POLL_INTERVAL = 15_000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const wasAuthenticatedRef = useRef(false);

  // ── Restore session on mount ───────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    fetch(API.auth.me, { credentials: 'include' })
      .then((res) => {
        if (!res.ok) throw new Error('not authenticated');
        return res.json() as Promise<MeResponse>;
      })
      .then((data) => {
        if (!cancelled) {
          setUser(data.user);
          wasAuthenticatedRef.current = true;
        }
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Periodic auth health-check ─────────────────────────────────────────
  // Only runs when user is authenticated. Clears user on failure so
  // ProtectedRoute immediately redirects to /login.
  useEffect(() => {
    if (!user) return;

    const id = setInterval(async () => {
      try {
        const res = await fetch(API.auth.me, { credentials: 'include' });
        if (!res.ok) throw new Error('expired');
      } catch {
        setUser(null);
        wasAuthenticatedRef.current = false;
      }
    }, AUTH_POLL_INTERVAL);
    return () => clearInterval(id);
  }, [user]);

  // ── Listen for 401 events from fetchJson ───────────────────────────────
  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      wasAuthenticatedRef.current = false;
    };
    window.addEventListener('auth:unauthorized', onUnauthorized);
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized);
  }, []);

  // ── Actions ────────────────────────────────────────────────────────────
  const login = useCallback(async (username: string, password: string) => {
    const res = await fetch(API.auth.login, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.detail ?? 'Login failed');
    }

    const data: LoginResponse = await res.json();
    setUser(data.user);
    wasAuthenticatedRef.current = true;
  }, []);

  const logout = useCallback(async () => {
    await fetch(API.auth.logout, {
      method: 'POST',
      credentials: 'include',
    }).catch(() => {});
    setUser(null);
    wasAuthenticatedRef.current = false;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isLoading,
      login,
      logout,
    }),
    [user, isLoading, login, logout]
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
