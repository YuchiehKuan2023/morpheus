import { BrandGraphList, EarlyReturn, GraphList, LocationMap, Tab } from '@/components';
import { BROWSER_ICON_MAP, OS_ICON_MAP } from '@/constants/shared';
import type { UserLocation } from '@/types';
import type { UserTabProps } from '@/types';
import type { FC } from 'react';

const DetectionsTab: FC<UserTabProps> = (props) => {
  const { detail, type, loading } = props;
  const { graph_context_combined: combined } = detail;

  if (loading)
    return (
      <Tab {...{ type }}>
        <EarlyReturn>Loading...</EarlyReturn>
      </Tab>
    );

  if (!combined) {
    return (
      <Tab {...{ type }}>
        <EarlyReturn>No detection context available...</EarlyReturn>
      </Tab>
    );
  }

  const {
    detected_ips,
    detected_devices,
    detected_browsers,
    detected_locations,
    detected_client_apps,
    detected_applications,
    detected_operating_systems,
    detected_location_coords,
  } = combined;

  // Build map locations — prefer coords stored alongside each anomaly's raw event,
  // fall back to matching against the user's baseline all_locations by city name.
  const baselineLocMap = new Map<string, UserLocation>(
    (detail.all_locations ?? []).map((l) => [l.city.toLowerCase(), l])
  );
  const mapLocations = detected_locations
    .map((locStr): UserLocation | null => {
      // Primary: direct coord lookup keyed by full "City, Country" string
      const direct = detected_location_coords[locStr];
      if (direct) {
        const city = locStr.split(',')[0].trim();
        const country = locStr.split(',').slice(1).join(',').trim();
        return { city, country, lat: direct.lat, lon: direct.lon, frequency: 1 };
      }
      // Fallback: match by city name against baseline all_locations
      const city = locStr.split(',')[0].trim();
      return baselineLocMap.get(city.toLowerCase()) ?? null;
    })
    .filter((l): l is UserLocation => l !== null)
    // deduplicate by city + country so distinct locations with the same city name
    // are not incorrectly collapsed across countries/regions
    .filter(
      (l, idx, arr) =>
        arr.findIndex(
          (o) =>
            `${o.city.trim().toLowerCase()}|${o.country.trim().toLowerCase()}` ===
            `${l.city.trim().toLowerCase()}|${l.country.trim().toLowerCase()}`
        ) === idx
    );

  const genericSections = [
    { label: 'IPs', items: detected_ips },
    { label: 'Devices', items: detected_devices },
    { label: 'Client Apps', items: detected_client_apps },
    { label: 'Applications', items: detected_applications },
  ].filter((s) => s.items.length > 0);

  return (
    <Tab {...{ type }}>
      {genericSections.map(({ label, items }) => (
        <div key={label}>
          <h3 className="text-sm font-semibold mb-1.5 text-muted-foreground uppercase tracking-wide flex items-center gap-2">
            {label}
            <span className="numbered-item">{items.length}</span>
          </h3>
          <GraphList items={items} />
        </div>
      ))}

      {detected_browsers.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-1.5 text-muted-foreground uppercase tracking-wide flex items-center gap-2">
            Browsers
            <span className="numbered-item">{detected_browsers.length}</span>
          </h3>
          <BrandGraphList items={detected_browsers} iconMap={BROWSER_ICON_MAP} />
        </div>
      )}

      {detected_operating_systems.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-1.5 text-muted-foreground uppercase tracking-wide flex items-center gap-2">
            Operating Systems
            <span className="numbered-item">{detected_operating_systems.length}</span>
          </h3>
          <BrandGraphList items={detected_operating_systems} iconMap={OS_ICON_MAP} />
        </div>
      )}

      {detected_locations.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-1.5 text-muted-foreground uppercase tracking-wide flex items-center gap-2">
            Locations
            <span className="numbered-item">{detected_locations.length}</span>
          </h3>
          <GraphList items={detected_locations} />
          {mapLocations.length > 0 && (
            <div className="mt-3">
              <LocationMap locations={mapLocations} height={320} />
            </div>
          )}
        </div>
      )}
    </Tab>
  );
};

export default DetectionsTab;
