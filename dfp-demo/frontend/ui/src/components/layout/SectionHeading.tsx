import type { FC, ReactNode } from 'react';

interface Props {
  title: ReactNode;
  subtitle: ReactNode;
}

const SectionHeading: FC<Props> = ({ title, subtitle }) => {
  return (
    <div className="mb-9 mt-9 flex flex-col gap-1 justify-center items-center text-center">
      <h2 className="text-2xl font-semibold text-gray-900">{title}</h2>
      <div className="text-sm text-gray-500">{subtitle}</div>
    </div>
  );
};

export default SectionHeading;
