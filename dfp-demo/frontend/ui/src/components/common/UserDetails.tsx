import type { MonitoredUser } from '@/types';
import type { FC } from 'react';

interface Props {
  user: MonitoredUser;
}

const UserDetails: FC<Props> = ({ user }) => {
  const {
    avatarColor,
    avatarUrl,
    avatarInitials,
    displayName,
    city,
    country,
    jobTitle,
    department,
  } = user;

  return (
    <div className="sim-event-card__meta">
      <div className="flex gap-5 glass-card glass-card--xs no-border no-shadow min-w-90 max-w-90">
        {/* Avatar */}
        <span
          className="sim-event-card__avatar anomaly-detail-user-avatar"
          {...(!avatarUrl
            ? { style: { backgroundColor: avatarColor || 'var(--brand-black)' } }
            : {})}
        >
          {avatarUrl ? (
            <img
              className="sim-event-card__avatar-img"
              src={`/avatar/${avatarUrl}`}
              alt={displayName ?? 'User'}
              draggable={false}
            />
          ) : (
            avatarInitials
          )}
        </span>
        {/* Details */}
        <span className="sim-event-card__name flex flex-col">
          <span className="mb-2 font-black">{displayName}</span>
          <span>
            <strong>Job Title</strong>: {jobTitle}
          </span>
          <span>
            <strong>Department</strong>: {department}
          </span>
          <span>
            <strong>Location</strong>: {city}, {country}
          </span>
        </span>
      </div>
    </div>
  );
};

export default UserDetails;
