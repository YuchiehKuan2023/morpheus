import type { FC, ReactNode } from 'react';

interface Props {
  title: ReactNode;
  description: ReactNode;
}

const PageHeader: FC<Props> = ({ title, description }) => {
  return (
    <div className="page-header ml-auto mr-auto text-center mb-8">
      <h2 className="text-2xl font-bold text-gray-900">{title}</h2>
      <p className="text-gray-600 mt-1">{description}</p>
    </div>
  );
};

export default PageHeader;
