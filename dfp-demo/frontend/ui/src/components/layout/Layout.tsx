import type { ReactNode } from 'react';
import { ConstellationBackground } from '../ui/constellation';
import { cn } from '@/utils';
import { TopNavigation } from '..';

interface LayoutProps {
  children: ReactNode;
  containerClassName?: string;
}

const Layout = ({ children, containerClassName }: LayoutProps) => {
  return (
    <>
      <TopNavigation />
      <ConstellationBackground
        className="bg-glass-overlay"
        nodeColor="rgba(156, 163, 175, 0.9)"
        lineColor="rgba(209, 213, 219, 0.9)"
        glow={false}
      >
        <div className="relative flex h-screen flex-col overflow-hidden">
          <main className="flex-1 flex flex-col overflow-auto dfp-main-content">
            <div className={cn('container flex-1 px-4 py-6 relative', containerClassName)}>
              {children}
            </div>
          </main>
        </div>
      </ConstellationBackground>
    </>
  );
};

export default Layout;
