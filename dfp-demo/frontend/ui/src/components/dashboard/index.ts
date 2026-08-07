/**
 * Dashboard component barrel — also re-exports ChartCard (GlassCard alias)
 * so platform sub-components can import it from '..'.
 */
export { default as ChartCard } from '../common/GlassCard';
export * from './platform';
