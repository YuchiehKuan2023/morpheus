import type { FC, PropsWithChildren } from 'react';

const EarlyReturn: FC<PropsWithChildren> = ({ children }) => (
  <div className="h-20 flex items-center justify-center text-sm text-muted-foreground">
    {children}
  </div>
);

export default EarlyReturn;
