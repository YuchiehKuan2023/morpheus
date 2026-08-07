import { Fragment, type FC } from 'react';

export const TagList: FC<{ items: string[] }> = ({ items }) => {
  return (
    <div className="flex flex-wrap gap-1.5 mt-1.5">
      {items.map((item, idx) => {
        const Comma = () => idx < items.length - 1 && <span>, </span>;
        return (
          <Fragment key={idx}>
            <span className="text-[12px]">
              <span className="font-semibold">{item[0]}</span> <span>({item[1]})</span>
              <Comma />
            </span>
          </Fragment>
        );
      })}
    </div>
  );
};

export const GraphList: FC<{ items: string[] }> = ({ items }) => {
  return (
    <div className="flex flex-wrap gap-1.5 mt-1.5">
      {items.map((item, idx) => {
        const Comma = () => idx < items.length - 1 && <span>, </span>;
        return (
          <Fragment key={idx}>
            <span className="text-[12px]">
              <span className="font-semibold">{item}</span>
              <Comma />
            </span>
          </Fragment>
        );
      })}
    </div>
  );
};
