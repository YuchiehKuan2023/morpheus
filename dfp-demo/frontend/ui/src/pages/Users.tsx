import { useEffect, useState, useCallback } from 'react';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { setUsers } from '../features/users/usersSlice';
import { api } from '../services/api';

export default function Users() {
  const dispatch = useAppDispatch();
  const { items } = useAppSelector((state) => state.users);
  const [loading, setLoading] = useState(true);

  const loadUsers = useCallback(async () => {
    try {
      const data = await api.getUsers();
      dispatch(setUsers(data));
    } catch (err) {
      console.error('Failed to load users:', err);
    } finally {
      setLoading(false);
    }
  }, [dispatch]);

  useEffect(() => {
    loadUsers();
    const interval = setInterval(loadUsers, 10000);
    return () => clearInterval(interval);
  }, [loadUsers]);

  const statusColors = {
    normal: 'bg-green-100 text-green-800',
    suspicious: 'bg-yellow-100 text-yellow-800',
    critical: 'bg-red-100 text-red-800',
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Users</h2>
          <p className="text-gray-600 mt-1">{items.length} users monitored</p>
        </div>
        <button
          onClick={loadUsers}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Users Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {items.length === 0 ? (
          <div className="col-span-full bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
            <p className="text-gray-500">
              No users found. Start training models to begin monitoring.
            </p>
          </div>
        ) : (
          items.map((user) => (
            <div
              key={user.username}
              className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center space-x-3">
                  <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center text-blue-600 font-semibold text-lg">
                    {user.username.substring(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-900">{user.username}</h3>
                    <p className="text-sm text-gray-500">User Profile</p>
                  </div>
                </div>
                <span
                  className={`px-2 py-1 text-xs font-semibold rounded-full ${
                    statusColors[user.status]
                  }`}
                >
                  {user.status}
                </span>
              </div>

              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Total Events:</span>
                  <span className="font-medium text-gray-900">{user.totalEvents}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Anomalies:</span>
                  <span className="font-medium text-gray-900">{user.anomalyCount}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Risk Score:</span>
                  <span className="font-mono font-medium text-gray-900">
                    {user.riskScore.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Last Seen:</span>
                  <span className="text-gray-500">{user.lastSeen}</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
