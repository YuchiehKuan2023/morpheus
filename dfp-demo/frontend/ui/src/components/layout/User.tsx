import { useAuth } from '@/contexts/useAuth';
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui';
import { LogOut, Search, Shield, User as UserIcon, Users } from 'lucide-react';
import type { FC } from 'react';
import { useNavigate } from 'react-router-dom';

const User: FC = () => {
  const { user, logout } = useAuth();

  const navigate = useNavigate();

  if (!user) return null;

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const roleParts = user.analyst_role ? user.analyst_role.split('_') : [];
  const formattedRole =
    roleParts.length > 1 ? `${roleParts[0].toUpperCase()} ${roleParts[1]}` : user.analyst_role;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="rounded-full outline-none top-navigation__user">
          <Avatar className="h-12 w-12 cursor-pointer">
            {user.avatar_url && (
              <AvatarImage
                src={`/avatar/${user.avatar_url}`}
                alt={user.display_name ?? user.username}
                className="rounded-full"
              />
            )}
            <AvatarFallback
              className="text-xs font-semibold text-white"
              style={{ backgroundColor: user.avatar_color ?? '#6366f1' }}
            >
              {user.avatar_initials ?? user.username.slice(0, 2).toUpperCase()}
            </AvatarFallback>
          </Avatar>
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="end"
        className="w-64 bg-white shadow-lg border border-gray-200 glass-card glass-card--xs"
      >
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-medium">{user.display_name ?? user.username}</span>
            <span className="text-xs text-muted-foreground">{formattedRole}</span>
          </div>
        </DropdownMenuLabel>
        <div className="separator -ml-2.5 -mr-2.5 mt-1.5 mb-1.5" />
        <DropdownMenuItem onClick={() => navigate('/profile')}>
          <UserIcon />
          Profile
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => navigate('/anomalies')}>
          <Shield />
          Anomalies
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => navigate('/investigations')}>
          <Search />
          Investigations
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => navigate('/users')}>
          <Users />
          Users
        </DropdownMenuItem>
        <div className="separator -ml-2.5 -mr-2.5 mt-1.5 mb-1.5" />
        <DropdownMenuItem onClick={handleLogout}>
          <LogOut />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

export default User;
