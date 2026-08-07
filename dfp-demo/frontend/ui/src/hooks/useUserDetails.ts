import type { TabType, UserDetailAction, UserDetailProps, UserDetailState } from '@/types/users';
import { useEffect, useReducer, useState } from 'react';
import { api } from '@/services/api';

function detailReducer(_: UserDetailState, action: UserDetailAction): UserDetailState {
  switch (action.type) {
    case 'reset':
      return { status: 'loading' };
    case 'success':
      return { status: 'success', data: action.payload };
    case 'not_found':
      return { status: 'error', message: 'User details were not found.' };
    case 'error':
      return { status: 'error', message: 'Failed to load user details.' };
  }
}

function useUserDetails({ user, open, onClose }: UserDetailProps) {
  const [activeTab, setActiveTab] = useState<TabType | string>('details');
  const [detailState, dispatch] = useReducer(detailReducer, { status: 'idle' });

  const username = user?.username ?? null;

  useEffect(() => {
    if (!open || !username) {
      return;
    }

    dispatch({ type: 'reset' });

    let cancelled = false;

    api
      .getUserFull(username)
      .then((data) => {
        if (cancelled) return;
        if (data) {
          dispatch({ type: 'success', payload: data });
        } else {
          dispatch({ type: 'not_found' });
        }
      })
      .catch(() => {
        if (!cancelled) dispatch({ type: 'error' });
      });

    return () => {
      cancelled = true;
    };
  }, [open, username]);

  if (!user) return null;

  const title = user.display_name ?? user.username;
  const loading = detailState.status === 'idle' || detailState.status === 'loading';
  const detail = detailState.status === 'success' ? detailState.data : null;
  const error = detailState.status === 'error' ? detailState.message : null;

  return {
    user,
    title,
    loading,
    detail,
    error,
    activeTab,
    open,
    setActiveTab,
    onClose,
  };
}

export default useUserDetails;
