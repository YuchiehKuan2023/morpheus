import type { TopUser, UserDetail } from '@/types/dashboard';
import type { SvgIcon } from '@/types/shared';
import type { MonitoredUser } from '@/types/simulation';

export const mapToUserDetail = (user: TopUser): MonitoredUser => {
  return {
    displayName: user.display_name,
    firstName: user.first_name,
    lastName: user.last_name,
    email: user.email,
    jobTitle: user.job_title,
    department: user.department,
    company: user.company,
    seniority: user.seniority,
    userRole: user.user_role,
    avatarUrl: user.avatar_url,
    avatarInitials: user.avatar_initials,
    avatarColor: user.avatar_color,
    city: user.primary_location_city,
    country: user.primary_location_country,
  };
};

export const getUserProfileDetails = (detail: UserDetail) => {
  return [
    { label: 'Email', value: detail.email },
    { label: 'Company', value: detail.company },
    { label: 'Department', value: detail.department },
    { label: 'Job Title', value: detail.job_title },
    { label: 'Seniority', value: detail.seniority },
    { label: 'Role', value: detail.user_role },
    {
      label: 'Location',
      value:
        detail.primary_location_city && detail.primary_location_country
          ? `${detail.primary_location_city}, ${detail.primary_location_country}`
          : (detail.primary_location_city ?? null),
    },
    {
      label: 'Work Hours',
      value:
        detail.work_hours_start != null && detail.work_hours_end != null
          ? `${String(detail.work_hours_start).padStart(2, '0')}:00 - ${String(detail.work_hours_end).padStart(2, '0')}:00`
          : null,
    },
    { label: 'Active Days', value: detail.active_days?.join(', ') ?? null },
    {
      label: 'Total Events',
      value: detail.total_events?.toLocaleString() ?? null,
    },
    { label: 'Primary OS', value: detail.primary_os },
    { label: 'Primary Browser', value: detail.primary_browser },
    { label: 'Primary Device', value: detail.primary_device },
  ];
};

export function getBrandIcon(name: string, map: Array<[string, SvgIcon]>): SvgIcon | null {
  const lower = name.toLowerCase();
  for (const [key, Icon] of map) {
    if (lower.includes(key)) return Icon;
  }
  return null;
}
