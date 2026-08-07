import type { FC } from 'react';
import type { UserTabProps } from '@/types';
import { LocationMap, UserSparkline, Tab, EarlyReturn } from '@/components';
import { getUserProfileDetails } from '@/utils/users';

const DetailsTab: FC<UserTabProps> = (props) => {
  const { detail, type, loading } = props;
  const { trend, devices, apps, all_locations } = detail;

  if (loading)
    return (
      <Tab {...{ type }}>
        <EarlyReturn>Loading...</EarlyReturn>
      </Tab>
    );

  return (
    <Tab {...{ type }}>
      <UserSparkline data={trend} height={88} />

      <div>
        <h3 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wide">
          Profile
        </h3>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2.5">
          {getUserProfileDetails(detail)
            .filter((r) => r.value)
            .map(({ label, value }) => (
              <div key={label} className="flex gap-2">
                <span className="text-xs text-muted-foreground min-w-22.5 shrink-0 w-25">
                  <strong>{label}</strong>:
                </span>
                <span className="text-xs">{value}</span>
              </div>
            ))}
        </div>
      </div>

      {devices && devices.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wide">
            Devices
          </h3>
          <div className="space-y-1.5">
            {devices.map((d) => (
              <div key={d.name} className="flex items-center justify-between text-xs">
                <span className="font-mono">{d.name}</span>
                <span className="dfp-badge">{d.count.toLocaleString()} events</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {apps && apps.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wide">
            Applications
          </h3>
          <div className="space-y-1.5">
            {apps.map((a) => (
              <div key={a.app} className="flex items-center justify-between text-xs">
                <span>{a.app}</span>
                <span className="dfp-badge">{a.count.toLocaleString()} events</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {all_locations && all_locations.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wide">
            Locations
          </h3>
          <LocationMap locations={all_locations} height={320} />
        </div>
      )}
    </Tab>
  );
};

export default DetailsTab;
