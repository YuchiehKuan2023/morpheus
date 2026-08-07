import { type FormEvent, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/useAuth';
import { ConstellationBackground } from '@/components/ui/constellation';
import { Button, Input, Label } from '@/components/ui';
import DeloitteLogo from '../assets/logo.svg';
import NvidiaLogo from '../assets/nvidia.svg';

export default function SignIn() {
  const { login, isAuthenticated, isLoading } = useAuth();
  const location = useLocation();
  const returnTo = (location.state as { returnTo?: string } | null)?.returnTo || '/dashboard';

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (isAuthenticated && !isLoading) {
    return <Navigate to={returnTo} replace />;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ConstellationBackground
      className="bg-glass-overlay"
      nodeColor="rgba(156, 163, 175, 0.9)"
      lineColor="rgba(209, 213, 219, 0.9)"
      glow={false}
    >
      <div className="flex min-h-screen items-center justify-center px-4">
        <form
          onSubmit={handleSubmit}
          autoComplete="off"
          className="glass-card glass-card--sm w-full max-w-sm rounded-2xl border border-white/10 bg-white/5 p-8 shadow-xl backdrop-blur-md"
        >
          <div className="mb-6 mt-4 flex flex-col items-center gap-2">
            <div className="flex w-full h-12 items-center justify-center gap-2">
              <div className="flex">
                <img
                  src={NvidiaLogo}
                  alt="NVIDIA Logo"
                  className="nvidia-logo h-8"
                  title="NVIDIA"
                />
              </div>
              <div className="flex">
                <img
                  src={DeloitteLogo}
                  alt="Deloitte Logo"
                  className="deloitte-logo h-8"
                  title="Deloitte"
                />
              </div>
            </div>
            <p className="text-sm text-gray-400">Sign in to your account</p>
          </div>

          {error && (
            <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          <div className="mb-4 space-y-1.5">
            <Label htmlFor="username" className="text-sm text-gray-300">
              Username
            </Label>
            <Input
              id="username"
              type="text"
              autoComplete="off"
              autoFocus
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="analyst@contoso.com"
              className="bg-white/5 border-white/10 text-black placeholder:text-gray-500"
            />
          </div>

          <div className="mb-6 space-y-1.5">
            <Label htmlFor="password" className="text-sm text-gray-300">
              Password
            </Label>
            <Input
              id="password"
              type="password"
              autoComplete="off"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="bg-white/5 border-white/10 text-black placeholder:text-gray-500"
            />
          </div>

          <Button type="submit" className="w-full" disabled={submitting || !username || !password}>
            {submitting ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      </div>
    </ConstellationBackground>
  );
}
