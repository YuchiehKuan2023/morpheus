/**
 * ReviewTab — shared analyst review panel used in both AnomalyDetailSheet
 * and AnomalyDetailDialog.  Provides assign, verdict submission, and review
 * history display.
 */
import { useState } from 'react';
import { UserPlus } from 'lucide-react';
import { Button, Label } from '@/components/ui';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge, GlassCard } from '@/components';
import { useAuth } from '@/contexts/useAuth';
import { api } from '@/services/api';
import type { AnomalyDetail } from '@/types';
import { formatDateTime, toTitleCase } from '@/utils';
import { VERDICT_OPTIONS } from '@/constants/anomalies';

// ── Helpers ──────────────────────────────────────────────────────────────────

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground font-medium">
        <Badge variant="lime">
          {value ? (typeof value === 'string' ? toTitleCase(value) : value) : '-'}
        </Badge>
      </dd>
    </>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

interface Props {
  detail: AnomalyDetail;
  onRefresh: () => void;
}

export function ReviewTab({ detail, onRefresh }: Props) {
  const { user } = useAuth();

  const [verdict, setVerdict] = useState('');
  const [analystNotes, setAnalystNotes] = useState('');
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [changingVerdict, setChangingVerdict] = useState(false);

  const isAdmin = user?.analyst_role === 'admin';
  const isAssignedToMe = detail.assignedTo === user?.id;
  const isUnassigned = detail.assignedTo == null;
  const hasVerdict = detail.analystVerdict != null;
  const canReview = isAssignedToMe || isUnassigned || isAdmin;
  const showForm = canReview && (!hasVerdict || changingVerdict);

  const handleAssign = async () => {
    setAssigning(true);
    try {
      await api.assignAnomaly(detail.anomalyId);
      setSuccess('Anomaly assigned to you');
      onRefresh();
    } catch {
      setSuccess(null);
    } finally {
      setAssigning(false);
    }
  };

  const handleSubmitReview = async () => {
    if (!verdict) return;
    setSubmitting(true);
    try {
      const result = await api.reviewAnomaly(
        detail.anomalyId,
        verdict,
        analystNotes,
        resolutionNotes
      );
      setSuccess(
        `Verdict submitted: ${verdict.replace('_', ' ')}${result.disagreement ? ' (disagrees with AI — flagged for retraining)' : ''}`
      );
      setChangingVerdict(false);
      onRefresh();
    } catch {
      setSuccess(null);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4 pl-2 pr-2">
      {/* Assignment status */}
      {isUnassigned && (
        <GlassCard
          title={<span className="text-lg">Assignment</span>}
          description={
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">This anomaly is unassigned.</p>
              <Button size="sm" onClick={handleAssign} disabled={assigning}>
                <UserPlus className="h-4 w-4 mr-1.5" />
                {assigning ? 'Assigning…' : 'Assign to me'}
              </Button>
            </div>
          }
          className="glass-card--xs no-border no-shadow"
        />
      )}

      {/* Previous review (if any) */}
      {hasVerdict && (
        <GlassCard
          title={<span className="text-lg">Review History</span>}
          description={
            <>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <Row label="Verdict" value={detail.analystVerdict?.replace('_', ' ')} />
                <Row
                  label="Reviewed At"
                  value={detail.reviewedAt ? formatDateTime(detail.reviewedAt) : null}
                />
                <Row
                  label="Reviewer"
                  value={detail.reviewedBy ? `Analyst #${detail.reviewedBy}` : null}
                />
                <Row label="Status" value={detail.status} />
                <Row
                  label="Resolved At"
                  value={detail.resolvedAt ? formatDateTime(detail.resolvedAt) : null}
                />
              </dl>
              <div className="separator -ml-3 -mr-3 mt-4 mb-4" />
              {detail.analystNotes && (
                <div className="mt-2">
                  <span className="text-sm text-muted-foreground/70 font-bold">
                    Analyst Notes:{' '}
                  </span>
                  <span className="text-sm text-muted-foreground">{detail.analystNotes}</span>
                </div>
              )}
              {detail.resolutionNotes && (
                <div className="mt-2">
                  <span className="text-sm text-muted-foreground/70 font-bold">
                    Resolution Notes:{' '}
                  </span>
                  <span className="text-sm text-muted-foreground">{detail.resolutionNotes}</span>
                </div>
              )}
              {canReview && !changingVerdict && (
                <div className="mt-3">
                  <div className="separator -ml-3 -mr-3 mt-4 mb-4" />
                  <Button
                    size="default"
                    className="bg-dark-lime text-white cursor-pointer"
                    onClick={() => setChangingVerdict(true)}
                  >
                    Change Verdict
                  </Button>
                </div>
              )}
            </>
          }
          className="glass-card--xs no-border no-shadow"
          separator
        />
      )}

      {/* Submit verdict form */}
      {showForm && (
        <GlassCard
          title={
            <span className="text-lg">{changingVerdict ? 'Change Verdict' : 'Submit Review'}</span>
          }
          description={
            <div className="space-y-4 mt-4">
              <div className="space-y-2">
                <Label className="text-muted-foreground pl-1 mb-2! flex">Verdict</Label>
                <Select value={verdict} onValueChange={setVerdict}>
                  <SelectTrigger className="bg-muted/50 border-border text-foreground">
                    <SelectValue placeholder="Select verdict..." />
                  </SelectTrigger>
                  <SelectContent className="z-400 glass-card glass-card--xs rounded-md! p-0!">
                    {VERDICT_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        <span>{opt.label}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground pl-1 mb-2! flex">Analysis Notes</Label>
                <textarea
                  className="w-full glass-card glass-card--xs rounded-md! bg-muted/50 text-foreground text-sm px-3 py-2 min-h-20 resize-y focus:outline-none placeholder:text-muted-foreground/50"
                  placeholder="Describe your analysis: what you investigated, evidence found, reasoning behind your verdict..."
                  value={analystNotes}
                  onChange={(e) => setAnalystNotes(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label className="text-muted-foreground pl-1 mb-2! flex">Resolution Notes</Label>
                <textarea
                  className="w-full glass-card glass-card--xs rounded-md! bg-muted/50 text-foreground text-sm px-3 py-2 min-h-20 resize-y focus:outline-none placeholder:text-muted-foreground/50"
                  placeholder="Summarise the resolution: actions taken, recommendations, any follow-up needed..."
                  value={resolutionNotes}
                  onChange={(e) => setResolutionNotes(e.target.value)}
                />
              </div>
              {!isUnassigned && !isAssignedToMe && (
                <p className="text-sm text-muted-foreground pl-1">
                  <strong>Note:</strong> This anomaly is currently assigned to another analyst.
                  Submitting a verdict will not change the assignment.
                </p>
              )}
              <Button
                onClick={handleSubmitReview}
                disabled={!verdict || !analystNotes.trim() || !resolutionNotes.trim() || submitting}
                className="w-full bg-pale-lime"
              >
                {submitting ? 'Submitting...' : 'Submit Verdict'}
              </Button>
            </div>
          }
          className="glass-card--xs no-border no-shadow"
          separator
        />
      )}

      {/* Success message */}
      {success && (
        <div className="rounded-lg bg-brand-lime/10 border border-brand-lime/20 px-4 py-3">
          <p className="text-sm text-brand-lime">{success}</p>
        </div>
      )}
    </div>
  );
}
