import { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { BotMessageSquare, LayoutDashboard, Network } from 'lucide-react';
import { cn } from '@/utils';
import { Notifications, Spinner, User } from '@/components';
import { useAppSelector } from '@/store/hooks';
import DeloitteLogo from '../../assets/logo.svg';
import DeloitteLogoSmall from '../../assets/logo-small.jpeg';
import NvidiaLogo from '../../assets/nvidia.svg';
import SimulationDrawer from './SimulationDrawer';

interface NavItem {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

const navItems: NavItem[] = [
  {
    title: 'Dashboard',
    href: '/dashboard',
    icon: LayoutDashboard,
  },
  {
    title: 'Knowledge Graph',
    href: '/graph',
    icon: Network,
  },
  {
    title: 'Conversational AI',
    href: '/chat',
    icon: BotMessageSquare,
  },
];

const TopNavigation = () => {
  const [isScrolled, setIsScrolled] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const simulationRunning = useAppSelector((s) => s.simulation.running);

  useEffect(() => {
    const handleScroll = () => {
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      setIsScrolled(scrollTop > 20);
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <>
      <nav className={cn('top-navigation', isScrolled && 'top-navigation--scrolled')}>
        <div className="top-navigation__container">
          <div className="top-navigation__items">
            {/* Logos */}
            <NavLink to="/" className="top-navigation__logo rounded-none!">
              <span className="top-navigation__logo-icon">
                <img src={NvidiaLogo} alt="NVIDIA Logo" className="nvidia-logo" title="NVIDIA" />
              </span>
              <span className="top-navigation__logo-icon">
                <img
                  src={DeloitteLogo}
                  alt="Deloitte Logo"
                  className="deloitte-logo"
                  title="Deloitte"
                />
                <img
                  src={DeloitteLogoSmall}
                  alt="Deloitte Logo"
                  className="deloitte-logo deloitte-logo--small"
                  title="Deloitte"
                />
              </span>
            </NavLink>

            {/* Navigation links */}
            {navItems.map((item) => (
              <NavLink
                key={item.href}
                to={item.href}
                className={({ isActive }) =>
                  cn('top-navigation__item', isActive && 'top-navigation__item--active')
                }
              >
                <span>{item.title}</span>
              </NavLink>
            ))}

            {/* Simulator toggle button */}
            <button
              className={cn(
                'top-navigation__item top-navigation__simulator-btn',
                drawerOpen && 'top-navigation__item--active'
              )}
              onClick={() => setDrawerOpen((v) => !v)}
              aria-label="Toggle Event Simulator"
              aria-expanded={drawerOpen}
            >
              {simulationRunning && <Spinner height={3} width={3} marginBottom={0} />}
              <span>Simulator</span>
            </button>

            {/* User navigation */}
            <Notifications />
            <User />
          </div>
        </div>
      </nav>

      <SimulationDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
};

export default TopNavigation;
