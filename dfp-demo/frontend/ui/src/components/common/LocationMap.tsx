import { type FC, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from 'react-leaflet';
import type { Map as LeafletMap, LatLngBoundsExpression } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { UserLocation } from '@/types';

interface FitBoundsProps {
  locations: UserLocation[];
}

// Inner component to auto-fit bounds after map mounts
const FitBounds: FC<FitBoundsProps> = ({ locations }) => {
  const map = useMap();
  useEffect(() => {
    if (locations.length === 0) return;
    if (locations.length === 1) {
      map.setView([locations[0].lat, locations[0].lon], 5);
      return;
    }
    const bounds: LatLngBoundsExpression = locations.map((l) => [l.lat, l.lon]);
    map.fitBounds(bounds, { padding: [32, 32] });
  }, [map, locations]);
  return null;
};

interface Props {
  locations: UserLocation[];
  height?: number;
}

const MAX_RADIUS = 18;
const MIN_RADIUS = 6;

const LocationMap: FC<Props> = ({ locations, height = 320 }) => {
  const mapRef = useRef<LeafletMap | null>(null);

  if (!locations || locations.length === 0) return null;

  const maxFreq = Math.max(...locations.map((l) => l.frequency), 1);

  const center: [number, number] =
    locations.length === 1
      ? [locations[0].lat, locations[0].lon]
      : [
          locations.reduce((s, l) => s + l.lat, 0) / locations.length,
          locations.reduce((s, l) => s + l.lon, 0) / locations.length,
        ];

  return (
    <div className="location-map" style={{ height }}>
      <MapContainer
        center={center}
        zoom={3}
        style={{ width: '100%', height: '100%' }}
        scrollWheelZoom={false}
        ref={mapRef}
        className="location-map__container"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />
        <FitBounds locations={locations} />
        {locations.map((loc, i) => {
          const radius = MIN_RADIUS + (loc.frequency / maxFreq) * (MAX_RADIUS - MIN_RADIUS);
          const isPrimary = i === 0;
          return (
            <CircleMarker
              key={`${loc.lat}-${loc.lon}`}
              center={[loc.lat, loc.lon]}
              radius={radius}
              pathOptions={{
                color: 'var(--brand-dark-lime)',
                fillColor: 'var(--brand-dark-lime)',
                fillOpacity: isPrimary ? 0.85 : 0.55,
                weight: isPrimary ? 2 : 1,
              }}
            >
              <Tooltip direction="top" offset={[0, -4]} opacity={0.95} className="rounded-2xl">
                <div className="location-map__tooltip">
                  <strong>
                    {loc.city}, {loc.country}
                  </strong>
                  <span>{loc.frequency.toLocaleString()} events</span>
                </div>
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
};

export default LocationMap;
