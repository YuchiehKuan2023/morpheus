import type { SvgIcon } from '@/types/shared';
import { getBrandIcon } from '@/utils/users';
import type { FC } from 'react';

interface Props {
  items: Array<[string, number]> | string[];
  iconMap: Array<[string, SvgIcon]> | string[];
}

const isCountTupleItems = (value: Props['items']): value is Array<[string, number]> =>
  value.every(
    (item): item is [string, number] =>
      Array.isArray(item) &&
      item.length === 2 &&
      typeof item[0] === 'string' &&
      typeof item[1] === 'number'
  );

const isIconTupleMap = (value: Props['iconMap']): value is Array<[string, SvgIcon]> =>
  value.every(
    (item): item is [string, SvgIcon] =>
      Array.isArray(item) && item.length === 2 && typeof item[0] === 'string'
  );

const BrandTagList: FC<Props> = ({ items, iconMap }) => {
  const tupleIconMap = isIconTupleMap(iconMap) ? iconMap : undefined;

  return (
    <div className="flex flex-wrap gap-1.5 mt-1.5">
      {isCountTupleItems(items)
        ? items.map(([name, count], idx) => {
            const Icon = tupleIconMap ? getBrandIcon(name, tupleIconMap) : undefined;
            return (
              <span key={idx} className="dfp-badge inline-flex items-center gap-1 text-[12px]">
                {Icon && (
                  <Icon
                    width={14}
                    height={14}
                    className="shrink-0"
                    color="var(--brand-dark-lime)"
                  />
                )}
                <span className="font-semibold">
                  {name} ({count})
                </span>
              </span>
            );
          })
        : items.map((name, idx) => {
            const Icon = tupleIconMap ? getBrandIcon(name, tupleIconMap) : undefined;
            return (
              <span key={idx} className="dfp-badge inline-flex items-center gap-1 text-[12px]">
                {Icon && (
                  <Icon
                    width={14}
                    height={14}
                    className="shrink-0"
                    color="var(--brand-dark-lime)"
                  />
                )}
                <span className="font-semibold">{name}</span>
              </span>
            );
          })}
    </div>
  );
};

export default BrandTagList;
