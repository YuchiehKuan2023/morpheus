import { cn } from '@/utils';
import type { FC, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';

export interface KeyPerformanceIndicator {
  title?: ReactNode;
  reduceValueSize?: boolean;
  value?: ReactNode;
  subtitle?: ReactNode;
  description?: ReactNode;
  size?: 'sm' | 'xs';
  variant?: 'dark' | 'lime';
  hero?: boolean;
  link?: string;
  className?: string;
  icons?: ReactNode[];
}

const KPICard: FC<KeyPerformanceIndicator> = (props) => {
  const { title, reduceValueSize, value, subtitle, size, variant, className, hero, link, icons } =
    props;

  const cardClass = cn(
    'kpi-card',
    size === 'sm' && 'kpi-card--sm',
    size === 'xs' && 'kpi-card--xs',
    variant === 'dark' && 'kpi-card--dark',
    variant === 'lime' && 'kpi-card--lime',
    hero && 'kpi-card--hero',
    className && className
  );

  if (hero) {
    return (
      <div className={cardClass}>
        {/* Show additional icons if provided (include icons) */}
        {icons && icons.length > 0 && (
          <div className="kpi-card__icons-wrapper">
            <div className="kpi-card__icons">
              {icons.map((icon, index) => (
                <div key={index} className="kpi-card__toggle kpi-card__icon">
                  {icon}
                </div>
              ))}
            </div>
            {link && (
              <div className="kpi-card__icons">
                <Link
                  to={link}
                  className="kpi-card__toggle kpi-card__icon"
                  aria-label="View all incidents"
                >
                  <ArrowUpRight className="h-6 w-6" />
                </Link>
              </div>
            )}
          </div>
        )}
        {/* Show link if provided (skip icons) */}
        {!icons?.length && link && (
          <div className="kpi-card__icons">
            <Link to={link} className="kpi-card__toggle" aria-label="View all incidents">
              <ArrowUpRight className="h-6 w-6" />
            </Link>
          </div>
        )}
        <div className="kpi-card__content">
          <div className="kpi-card__value-container">
            <div className={cn('kpi-card__title', reduceValueSize ?? 'kpi-card__value-reduced')}>
              {title}
            </div>
          </div>

          <div className="kpi-card__value">
            <div>{typeof value === 'number' ? value.toLocaleString() : value}</div>
            {subtitle && <div className="kpi-card__subtitle">{subtitle}</div>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={cardClass}>
      <div className="kpi-card__content">
        <div className="kpi-card__value-container">
          <div className={cn('kpi-card__value', reduceValueSize && 'kpi-card__value--reduced')}>
            {typeof value === 'number' ? value.toLocaleString() : value}
          </div>
          <div className="kpi-card__title">{title}</div>
        </div>

        {subtitle && <div className="kpi-card__subtitle">{subtitle}</div>}
      </div>
    </div>
  );
};

export default KPICard;
