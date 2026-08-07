import type { AssignedAnalyst } from '@/types/simulation';
import { toTitleCase } from '@/utils';
import type { FC } from 'react';

interface Props {
  analyst: AssignedAnalyst;
}

export const AnalystCard: FC<Props> = (props) => {
  const { analyst } = props;
  const { displayName, role, level, avatarUrl, avatarInitials, avatarColor } = analyst;

  const roleParts = role.split('_');
  const [rolePrefix, roleSuffix] = roleParts;
  const jobTitle =
    roleSuffix && rolePrefix
      ? `${rolePrefix.toUpperCase()} ${toTitleCase(roleSuffix)}`.trim()
      : toTitleCase(role).trim();

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
          <span>
            <h3 className="font-black mb-2">Case Analyst</h3>
          </span>
          <span>
            <strong>Name</strong>: {displayName}
          </span>
          <span>
            <strong>Job Title</strong>: {jobTitle}
          </span>
          <span>
            <strong>Level</strong>: {level}
          </span>
        </span>
      </div>
    </div>
  );
};
