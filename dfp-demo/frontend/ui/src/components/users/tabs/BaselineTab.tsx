import { Badge, BrandTagList, KPICard, LocationMap, Tab, TagList, EarlyReturn } from '@/components';
import { BROWSER_ICON_MAP, OS_ICON_MAP } from '@/constants/shared';
import { ENTITY_GROUPS } from '@/constants/users';
import type { UserTabProps } from '@/types';
import { formatDate, toTitleCase } from '@/utils';
import type { FC } from 'react';

const BaselineTab: FC<UserTabProps> = (props) => {
  const { detail, type, loading } = props;
  const { user_baseline: baseline } = detail;

  if (loading)
    return (
      <Tab {...{ type }}>
        <EarlyReturn>Loading...</EarlyReturn>
      </Tab>
    );

  if (!baseline)
    return (
      <Tab {...{ type }}>
        <EarlyReturn>No baseline data available...</EarlyReturn>
      </Tab>
    );

  const {
    baseline_strength,
    first_event,
    last_event,
    total_events,
    activity_hours_utc,
    active_days_of_week,
  } = baseline;

  const strength = baseline_strength as string | undefined;
  const firstEvent = first_event as string | undefined;
  const lastEvent = last_event as string | undefined;
  const totalEvents = total_events as number | undefined;

  const activityHours = activity_hours_utc as
    | { typical_range?: string; peak_hours?: number[]; off_hours?: number[] }
    | undefined;

  // active_days_of_week = { distribution: {Monday: 150, ...}, typical_days: [...] }
  const activeDaysDist = (
    active_days_of_week as { distribution?: Record<string, number> } | undefined
  )?.distribution;

  return (
    <Tab {...{ type }}>
      <div>
        <div className="grid grid-cols-4 gap-4 pl-1 pr-1">
          {strength && (
            <KPICard
              title="Baseline Strength"
              value={
                <Badge {...{ ...(strength === 'strong' ? { variant: 'lime' } : {}) }}>
                  {toTitleCase(strength)}
                </Badge>
              }
              size="xs"
              className="no-border no-shadow"
            />
          )}

          {totalEvents != null && (
            <KPICard
              title="Total Events"
              value={<Badge>{totalEvents.toLocaleString()}</Badge>}
              size="xs"
              className="no-border no-shadow"
            />
          )}

          {firstEvent && (
            <KPICard
              title="First Event"
              value={<Badge>{formatDate(firstEvent)}</Badge>}
              size="xs"
              className="no-border no-shadow"
            />
          )}

          {lastEvent && (
            <KPICard
              title="Last Event"
              value={<Badge>{formatDate(lastEvent)}</Badge>}
              size="xs"
              className="no-border no-shadow"
            />
          )}
        </div>
      </div>

      {activityHours && (
        <div>
          <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wide">
            Activity Hours (UTC)
          </h3>
          <div className="flex flex-wrap gap-2 text-xs">
            {activityHours.typical_range && <Badge>{activityHours.typical_range}</Badge>}
            {activityHours.peak_hours && activityHours.peak_hours.length > 0 && (
              <span className="rounded bg-muted/60 px-2 py-1 text-muted-foreground">
                Peak: {activityHours.peak_hours.map((h) => `${h}:00`).join(', ')}
              </span>
            )}
          </div>
        </div>
      )}

      {activeDaysDist && (
        <div>
          <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wide">
            Active Days of Week
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(activeDaysDist).map(([day, count]) => (
              <Badge key={day} variant="lime">
                {day} ({count})
              </Badge>
            ))}
          </div>
        </div>
      )}

      {ENTITY_GROUPS.map(({ key, label }) => {
        const raw = baseline[key] as
          | {
              count?: number;
              all?: string[];
              most_common?: [string, number][];
              coordinates?: [string, number, number][];
            }
          | undefined;
        const items = raw?.all;
        if (!items || items.length === 0) return null;
        const topItem = raw?.most_common?.[0]?.[0];

        // Build LocationMap data from the baseline's own coordinates + frequencies.
        const baselineMapLocations =
          key === 'locations' && raw?.coordinates && raw.coordinates.length > 0
            ? (() => {
                // items is [locStr, count][] at runtime (Python sends tuples)
                const allLocs = items as unknown as [string, number][];
                const normalizeCity = (value: string) =>
                  value.split(', ')[0]?.trim().toLowerCase() ?? '';
                const freqMap: Record<string, number> = {};
                allLocs.forEach(([locStr, count]) => {
                  const cityKey = normalizeCity(locStr);
                  if (cityKey) freqMap[cityKey] = count;
                });
                return raw.coordinates!.map(([city, lat, lon]) => {
                  const cityKey = city.trim().toLowerCase();
                  const fullStr =
                    allLocs.find(([locStr]) => normalizeCity(locStr) === cityKey)?.[0] ?? '';
                  const parts = fullStr.split(', ');
                  return {
                    city,
                    country: parts.at(-1) ?? '',
                    lat,
                    lon,
                    frequency: freqMap[cityKey] ?? 1,
                  };
                });
              })()
            : null;

        return (
          <div key={key}>
            <h3 className="text-sm font-semibold mb-1.5 text-muted-foreground uppercase tracking-wide flex items-center gap-2">
              {label}
              {raw?.count != null && <span className="numbered-item">{raw.count}</span>}
              {topItem && (
                <span className="text-xs font-normal normal-case text-muted-foreground">
                  (most common: <span className="text-foreground">{topItem}</span>)
                </span>
              )}
            </h3>
            {baselineMapLocations && (
              <div className="mb-2">
                <LocationMap locations={baselineMapLocations} height={320} />
              </div>
            )}
            {key === 'browsers' && <BrandTagList items={items} iconMap={BROWSER_ICON_MAP} />}
            {key === 'operating_systems' && <BrandTagList items={items} iconMap={OS_ICON_MAP} />}
            {key !== 'locations' && key !== 'browsers' && key !== 'operating_systems' && (
              <TagList items={items} />
            )}
          </div>
        );
      })}
    </Tab>
  );
};

export default BaselineTab;
