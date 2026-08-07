import { createContext, useContext, type FC, useState } from 'react';
import type { TopUser } from '@/types';
import { Badge, UserDialog } from '@/components';
import { formatDate } from '@/utils';
import { MapPin } from 'lucide-react';

// ── Context ───────────────────────────────────────────────────────────────────

interface UserCardContextValue {
  user: TopUser;
  onOpen: () => void;
}

const UserCardContext = createContext<UserCardContextValue | null>(null);

function useUserCard() {
  const ctx = useContext(UserCardContext);
  if (!ctx) throw new Error('UserCard sub-components must be used inside <UserCard>');
  return ctx;
}

// ── Sub-components ────────────────────────────────────────────────────────────

const Avatar: FC = () => {
  const { user } = useUserCard();
  const { avatar_color, avatar_url, avatar_initials, username, display_name } = user;

  return (
    <div
      className="user-card__avatar"
      style={{ backgroundColor: avatar_color ?? '#8a8a8a', overflow: 'hidden' }}
    >
      {avatar_url ? (
        <img
          src={`/avatar/${avatar_url}`}
          alt={display_name ?? username}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      ) : (
        <span style={{ color: 'white' }}>
          {avatar_initials ?? username.slice(0, 2).toUpperCase()}
        </span>
      )}
    </div>
  );
};

const Header: FC = () => {
  const { user } = useUserCard();
  return (
    <div className="user-card__header-info">
      <div className="user-card__name">{user.display_name}</div>
      <div className="user-card__email">{user.email}</div>
    </div>
  );
};

const Info: FC = () => {
  const { user } = useUserCard();

  const roleParts: string[] = [];

  if (user.job_title) {
    roleParts.push(user.job_title);

    if (user.department) {
      roleParts.push(`(${user.department})`);
    }
  } else if (user.department) {
    roleParts.push(user.department);
  }

  const roleText = roleParts.length > 0 ? roleParts.join(' ') : '—';

  const seniorityText = user.seniority ?? '—';

  return (
    <div className="user-card__user-info">
      <div className="user-card__user-details">
        <div className="user-card__user-type">
          <span className="block">Role: {roleText}</span>
          <span className="block">Seniority: {seniorityText}</span>
        </div>
        <div className="user-card__user-location">
          <MapPin className="w-4" />
          {user.primary_location_city}, {user.primary_location_country}
        </div>
      </div>
    </div>
  );
};

const Metrics: FC = () => {
  const { user } = useUserCard();
  return (
    <div className="user-card__metrics gap-2 flex">
      <Badge>{user.total_events} events</Badge>
      <Badge>{user.anomaly_count} anomalies</Badge>
      <Badge>{user.critical_count} critical</Badge>
      <Badge>{user.avg_anomaly_score.toFixed(1)} avg score</Badge>
    </div>
  );
};

const Footer: FC = () => {
  const { user } = useUserCard();
  return (
    <div className="user-card__footer">
      <div className="user-card__status">
        <div className="user-card__status-text">
          Last anomaly: {formatDate(user.last_anomaly_at)}
        </div>
      </div>
    </div>
  );
};

// ── Root ──────────────────────────────────────────────────────────────────────

interface UserCardComponent extends FC<{ user: TopUser }> {
  Avatar: typeof Avatar;
  Header: typeof Header;
  Info: typeof Info;
  Metrics: typeof Metrics;
  Footer: typeof Footer;
}

const UserCard: UserCardComponent = ({ user }) => {
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<TopUser | null>(null);

  const onOpen = () => {
    setSelectedUser(user);
    setIsDialogOpen(true);
  };

  const onClose = () => {
    setIsDialogOpen(false);
    setSelectedUser(null);
  };

  return (
    <UserCardContext.Provider value={{ user, onOpen }}>
      <div className="user-card-wrapper relative">
        <button className="user-card__toggle" onClick={onOpen} aria-label="View user details">
          <Avatar />
        </button>

        <div className="user-card dropdown">
          <div className="user-card__header">
            <Header />
          </div>
          <div className="user-card__body">
            <Info />
            <Metrics />
          </div>
          <Footer />
        </div>
      </div>

      <UserDialog user={selectedUser} open={isDialogOpen} onClose={onClose} />
    </UserCardContext.Provider>
  );
};

UserCard.Avatar = Avatar;
UserCard.Header = Header;
UserCard.Info = Info;
UserCard.Metrics = Metrics;
UserCard.Footer = Footer;

export default UserCard;
