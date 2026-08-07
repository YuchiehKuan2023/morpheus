import { AnomalyDetailDialog, GridCols, Tab, EarlyReturn, Spinner } from '@/components';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui';
import type { UserDetailAnomaly, PaginatedUserAnomalies } from '@/types';
import type { TabType } from '@/types/users';
import { resetBtnClass, ANOMALIES_TAB_SORT_OPTIONS as SORT_OPTIONS } from '@/constants/users';
import { formatDateTime, toTitleCase } from '@/utils';
import { api } from '@/services/api';
import { useState, useEffect, useCallback, useRef, type FC } from 'react';
import { ChevronLeft, ChevronRight, RotateCcw } from 'lucide-react';
import { Control } from '.';

const triggerClass =
  'glass-card glass-card--xs no-border no-shadow text-xs rounded-md! h-auto py-1.5 px-2 w-44 [&>span]:truncate';

interface AnomaliesTabProps {
  username: string;
  type: TabType;
  loading?: boolean;
}

const AnomaliesTab: FC<AnomaliesTabProps> = ({ username, type, loading: parentLoading }) => {
  const [data, setData] = useState<PaginatedUserAnomalies | null>(null);
  const [fetching, setFetching] = useState(true);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState('timestamp');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [rootCause, setRootCause] = useState('');
  const [subCategory, setSubCategory] = useState('');
  const [selectedAnomalyId, setSelectedAnomalyId] = useState<string | null>(null);

  const initialLoad = useRef(true);

  const fetchAnomalies = useCallback(async () => {
    setFetching(true);
    try {
      const result = await api.getUserAnomalies(username, {
        page,
        pageSize: 9,
        sortBy,
        sortDir,
        rootCause: rootCause || undefined,
        subCategory: subCategory || undefined,
      });
      setData(result);
      initialLoad.current = false;
    } catch {
      if (initialLoad.current) setData(null);
    } finally {
      setFetching(false);
    }
  }, [username, page, sortBy, sortDir, rootCause, subCategory]);

  useEffect(() => {
    fetchAnomalies();
  }, [fetchAnomalies]);

  // Reset page when filters/sort change
  const handleSortChange = (value: string) => {
    setSortBy(value);
    setPage(1);
  };
  const handleSortDirToggle = () => {
    setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    setPage(1);
  };
  const handleRootCauseChange = (value: string) => {
    setRootCause(value);
    setPage(1);
  };
  const handleSubCategoryChange = (value: string) => {
    setSubCategory(value);
    setPage(1);
  };
  const hasActiveFilters = rootCause || subCategory || sortBy !== 'timestamp' || sortDir !== 'desc';
  const handleReset = () => {
    setRootCause('');
    setSubCategory('');
    setSortBy('timestamp');
    setSortDir('desc');
    setPage(1);
  };

  if (parentLoading || (initialLoad.current && fetching))
    return (
      <Tab {...{ type }}>
        <EarlyReturn>Loading...</EarlyReturn>
      </Tab>
    );

  if (!data || (data.items.length === 0 && !fetching))
    return (
      <Tab {...{ type }}>
        <EarlyReturn>No anomalies found.</EarlyReturn>
      </Tab>
    );

  return (
    <>
      <Tab {...{ type }}>
        <div className="separator" />
        {/* Controls */}
        <div className="anomalies-controls flex flex-col items-center justify-center">
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {/* Sort */}
            <Control
              label="Sort"
              control={
                <Select value={sortBy} onValueChange={handleSortChange}>
                  <SelectTrigger className={triggerClass}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent
                    portal={false}
                    className="z-400 glass-card glass-card--xs rounded-md! p-0!"
                  >
                    {SORT_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              }
              actions={
                <button
                  className="dfp-btn dfp-btn--xs dfp-btn--ghost"
                  onClick={handleSortDirToggle}
                  title={sortDir === 'desc' ? 'Descending' : 'Ascending'}
                >
                  {sortDir === 'desc' ? '↓' : '↑'}
                </button>
              }
            />

            {/* Root Cause filter */}
            {data.filters.rootCauses.length > 0 && (
              <Control
                label="Root Cause"
                control={
                  <Select
                    value={rootCause || '_all'}
                    onValueChange={(v) => handleRootCauseChange(v === '_all' ? '' : v)}
                  >
                    <SelectTrigger className={triggerClass}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent
                      portal={false}
                      className="z-400 glass-card glass-card--xs rounded-md! p-0!"
                    >
                      <SelectItem value="_all">All</SelectItem>
                      {data.filters.rootCauses.map((rc) => (
                        <SelectItem key={rc.value} value={rc.value} disabled={rc.count === 0}>
                          {rc.value} ({rc.count})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                }
              />
            )}

            {/* Sub Category filter */}
            {data.filters.subCategories.length > 0 && (
              <Control
                label="Category"
                control={
                  <Select
                    value={subCategory || '_all'}
                    onValueChange={(v) => handleSubCategoryChange(v === '_all' ? '' : v)}
                  >
                    <SelectTrigger className={triggerClass}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent
                      portal={false}
                      className="z-400 glass-card glass-card--xs rounded-md! p-0!"
                    >
                      <SelectItem value="_all">All</SelectItem>
                      {data.filters.subCategories.map((sc) => (
                        <SelectItem key={sc.value} value={sc.value} disabled={sc.count === 0}>
                          {sc.value} ({sc.count})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                }
              />
            )}

            {/* Reset */}
            {hasActiveFilters && (
              <Control
                label="Reset"
                control={
                  <button className={resetBtnClass} onClick={handleReset} title="Reset all filters">
                    <RotateCcw width={12} height={12} /> Reset
                  </button>
                }
                options={{ hideLabel: true }}
              />
            )}

            {/* Inline loading indicator */}
            {fetching && (
              <Control
                label="Spinner"
                control={<Spinner {...{ height: 4, width: 4, marginBottom: 0 }} />}
                options={{ hideLabel: true }}
              />
            )}
          </div>
        </div>
        <div className="separator" />

        {/* Grid — dim while loading to signal refresh without hiding content */}
        <div
          className={
            fetching ? 'opacity-50 pointer-events-none transition-opacity' : 'transition-opacity'
          }
        >
          <GridCols cols={3} className="gap-4">
            {data.items.map((a: UserDetailAnomaly) => {
              const {
                anomaly_id,
                anomaly_score,
                severity,
                status,
                sub_category: cat,
                root_cause: cause,
                risk_score,
                timestamp,
              } = a;

              return (
                <button
                  key={anomaly_id}
                  type="button"
                  className="glass-card glass-card--xs no-border no-shadow text-left cursor-pointer hover:ring-1 hover:ring-primary/40 transition-shadow"
                  onClick={() => setSelectedAnomalyId(anomaly_id)}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-4">
                    <span className="dfp-badge">{toTitleCase(severity ?? 'UNKNOWN')}</span>
                    <span className="dfp-badge lime">{toTitleCase(status.replace(/_/g, ' '))}</span>
                  </div>
                  <div className="grid grid-cols-1 gap-x-4 gap-y-1 text-xs">
                    {cause && (
                      <div>
                        <span className="text-muted-foreground font-bold">Root cause: </span>
                        {cause}
                      </div>
                    )}
                    {cat && (
                      <div>
                        <span className="text-muted-foreground font-bold">Category: </span>
                        {cat}
                      </div>
                    )}
                    <div>
                      <span className="text-muted-foreground font-bold">Score: </span>
                      {anomaly_score.toFixed(2)}
                    </div>
                    {risk_score != null && (
                      <div>
                        <span className="text-muted-foreground font-bold">Risk: </span>
                        {risk_score.toFixed(1)}
                      </div>
                    )}
                    <div>
                      <span className="text-muted-foreground font-bold">Time: </span>
                      {formatDateTime(timestamp)}
                    </div>
                  </div>
                </button>
              );
            })}
          </GridCols>
        </div>
      </Tab>
      {/* Pagination */}
      {data.totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-4 text-xs">
          <button
            className="dfp-btn dfp-btn--xs dfp-btn--ghost inline-flex items-center gap-1"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            <ChevronLeft width={12} height={12} /> Prev
          </button>
          <span className="text-muted-foreground">
            {page} / {data.totalPages}
          </span>
          <button
            className="dfp-btn dfp-btn--xs dfp-btn--ghost inline-flex items-center gap-1"
            onClick={() => setPage((p) => Math.min(data.totalPages, p + 1))}
            disabled={page === data.totalPages}
          >
            Next <ChevronRight width={12} height={12} />
          </button>
        </div>
      )}

      <AnomalyDetailDialog
        anomalyId={selectedAnomalyId}
        open={selectedAnomalyId !== null}
        onClose={() => setSelectedAnomalyId(null)}
      />
    </>
  );
};

export default AnomaliesTab;
