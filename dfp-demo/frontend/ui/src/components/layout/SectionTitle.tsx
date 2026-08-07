import type { FC } from 'react';

interface Props {
  title: string;
  description?: string;
}

const SectionTitle: FC<Props> = ({ title, description }) => {
  return (
    <div className="section-title">
      <div className="pl-2 font-bold">{title}</div>
      {description && <div className="pl-2 text-sm text-gray-400 mt-0.5">{description}</div>}
    </div>
  );
};

export default SectionTitle;
