import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/useAuth';
import { Spinner } from '@/components';

export default function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return isAuthenticated ? (
    <Outlet />
  ) : (
    <Navigate to="/login" replace state={{ returnTo: location.pathname + location.search }} />
  );
}
