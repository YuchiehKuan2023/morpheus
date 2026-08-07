import type { SvgIcon } from '@/types/shared';
import { getBrandIcon } from '@/utils/users';
import type { FC } from 'react';

const BrandGraphList: FC<{ items: string[]; iconMap: Array<[string, SvgIcon]> }> = ({
  items,
  iconMap,
}) => (
  <div className="flex flex-wrap gap-1.5 mt-1.5">
    {items.map((name, idx) => {
      const Icon = getBrandIcon(name, iconMap);
      return (
        <span key={idx} className="dfp-badge inline-flex items-center gap-1 text-[12px]">
          {Icon && (
            <Icon width={14} height={14} className="shrink-0" color="var(--brand-dark-lime)" />
          )}
          <span className="font-semibold">{name}</span>
        </span>
      );
    })}
  </div>
);

export default BrandGraphList;
