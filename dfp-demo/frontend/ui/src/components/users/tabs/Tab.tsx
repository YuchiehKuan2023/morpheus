import type { FC, PropsWithChildren } from 'react';
import { TabsContent } from '@radix-ui/react-tabs';
import type { TabType } from '@/types';

const Tab: FC<PropsWithChildren & { type: TabType }> = ({ children, type }) => {
  return (
    <TabsContent
      value={type}
      className="flex-1 mt-4 overflow-auto data-[state=inactive]:hidden pb-4"
    >
      <div className="space-y-6">{children}</div>
    </TabsContent>
  );
};

export default Tab;
