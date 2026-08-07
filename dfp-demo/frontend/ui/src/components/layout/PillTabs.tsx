import type { FC, ReactNode } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui';
import { cn } from '@/utils';

export interface PillTab {
  id: string;
  label: string;
  icon?: ReactNode;
}

export interface PillTabAction {
  content: ReactNode;
  onClick: () => void;
  position?: 'left' | 'right';
  className?: string;
}

interface Props {
  tabs: PillTab[];
  value: string;
  onValueChange: (id: string) => void;
  /** Content area — use <TabsContent value="…"> blocks */
  children: ReactNode;
  /** Extra class applied to the root <Tabs> element */
  className?: string;
  /** Extra class applied to the pill nav wrapper div */
  navClassName?: string;
  /** Use the compact (smaller padding) variant */
  compact?: boolean;
  /** Optional action button rendered inside the pill bar */
  action?: PillTabAction;
}

const PillTabs: FC<Props> = ({
  tabs,
  value,
  onValueChange,
  children,
  className,
  navClassName,
  compact = false,
  action,
}) => {
  const hasAction = !!action;
  const actionLeft = hasAction && action.position === 'left';
  const actionRight = hasAction && action.position !== 'left';

  return (
    <Tabs value={value} onValueChange={onValueChange} className={cn('flex flex-col', className)}>
      <div className={cn('flex justify-center shrink-0', navClassName)}>
        <TabsList
          className={cn(
            'tabs-pill-container',
            compact && 'tabs-pill-container--compact',
            actionLeft && 'tabs-pill-container--action-left',
            actionRight && hasAction && 'tabs-pill-container--action-right'
          )}
        >
          {actionLeft && (
            <button
              type="button"
              onClick={action.onClick}
              className={cn('tabs-pill-action tabs-pill-action--left', action.className)}
            >
              {action.content}
            </button>
          )}
          {tabs.map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id}>
              {tab.icon && <span className="mr-1.5 inline-flex items-center">{tab.icon}</span>}
              {tab.label}
            </TabsTrigger>
          ))}
          {actionRight && hasAction && (
            <button
              type="button"
              onClick={action.onClick}
              className={cn('tabs-pill-action tabs-pill-action--right', action.className)}
            >
              {action.content}
            </button>
          )}
        </TabsList>
      </div>
      {children}
    </Tabs>
  );
};

export { TabsContent };
export default PillTabs;
