import { useInterviewAdminQuality } from '@/hooks/use-cs-interview-request';
import { InterviewShell, PageHeading } from '@/pages/cs-interview/components';
import { Routes } from '@/routes';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border-button bg-bg-card p-4">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="mt-2 font-mono text-2xl font-semibold tracking-[-0.03em]">
        {value}
      </div>
      {hint && <div className="mt-1 text-[11px] text-text-secondary">{hint}</div>}
    </div>
  );
}

function formatRate(value?: number): string {
  if (value === undefined || value === null) return '—';
  return `${(value * 100).toFixed(2)}%`;
}

export default function Quality() {
  const { t } = useTranslation();
  const { data, isPending, error } = useInterviewAdminQuality();

  if (isPending) return <InterviewShell><div className="p-8 text-text-secondary">Loading…</div></InterviewShell>;
  if (error) {
    return (
      <InterviewShell>
        <div className="p-8 text-state-error">
          {t('csInterview.admin.unauthorized', { defaultValue: 'Administrator access required.' })}
        </div>
      </InterviewShell>
    );
  }

  const latency = Object.entries(data?.latencyP50P95 ?? {});
  return (
    <InterviewShell>
      <PageHeading
        eyebrow="ops console"
        title={t('csInterview.admin.qualityTitle', { defaultValue: 'Quality overview' })}
        description={t('csInterview.admin.qualityDescription', {
          defaultValue: 'SLOs, quality, latency, token cost and version distribution from operational truth.',
        })}
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label={t('csInterview.admin.sessionSuccess', { defaultValue: 'Session success' })}
          value={formatRate(data?.sessionSuccessRate)}
          hint={`${data?.sessionCount ?? 0} sessions`}
        />
        <StatTile
          label={t('csInterview.admin.sessionFailures', { defaultValue: 'Session failures' })}
          value={String(data?.sessionFailureCount ?? 0)}
        />
        <StatTile
          label={t('csInterview.admin.answers', { defaultValue: 'Answers received' })}
          value={String(data?.answerRequestCount ?? 0)}
        />
        <StatTile
          label={t('csInterview.admin.estimatedCost', { defaultValue: 'Estimated cost (USD)' })}
          value={String(data?.estimatedCostUsd ?? 0)}
        />
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatTile label="JD requirement coverage" value={formatRate(data?.jdRequirementCoverage)} />
        <StatTile label="Judge consistency" value={formatRate(data?.judgeConsistencyRate)} />
        <StatTile label="Follow-up rate" value={formatRate(data?.followupRate)} />
        <StatTile label="Evidence refusal rate" value={formatRate(data?.evidenceRefusalRate)} />
        <StatTile label="Runner failure rate" value={formatRate(data?.runnerFailureRate)} />
        <StatTile label="Unknown model costs" value={String(data?.costUnknownCount ?? 0)} />
      </div>

      <section className="mt-8 rounded-lg border border-border-button p-4">
        <h3 className="mb-3 text-sm font-semibold">SLO alerts</h3>
        {(data?.alerts ?? []).length === 0 && (
          <div className="text-sm text-text-secondary">No alert evaluations yet.</div>
        )}
        {(data?.alerts ?? []).map((alert) => (
          <div key={alert.name} className="flex flex-wrap items-center justify-between gap-3 border-b border-border-button py-2 text-sm last:border-b-0">
            <div>
              <span className="font-mono text-xs">{alert.name}</span>
              <span className="ml-2 text-text-secondary">
                {alert.insufficient ? 'insufficient samples' : `${alert.value ?? '—'} ${alert.operator} ${alert.target}`}
              </span>
            </div>
            <a
              href={alert.runbook}
              className={alert.breached ? 'text-state-error underline' : 'text-text-secondary underline'}
              target="_blank"
              rel="noreferrer"
            >
              {alert.breached ? `${alert.level} breach` : 'runbook'}
            </a>
          </div>
        ))}
      </section>

      <div className="mt-8 grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border-button p-4">
          <h3 className="mb-3 text-sm font-semibold">{t('csInterview.admin.stageLatency', { defaultValue: 'Stage latency (P50 / P95 ms)' })}</h3>
          {latency.length === 0 && <div className="text-sm text-text-secondary">No latency samples yet.</div>}
          {latency.map(([stage, value]) => (
            <div key={stage} className="flex items-center justify-between border-b border-border-button py-2 text-sm last:border-b-0">
              <span className="text-text-secondary">{stage}</span>
              <span className="font-mono">
                {value.p50 ?? '—'} / {value.p95 ?? '—'}
              </span>
            </div>
          ))}
        </div>
        <div className="rounded-lg border border-border-button p-4">
          <h3 className="mb-3 text-sm font-semibold">{t('csInterview.admin.stageFailures', { defaultValue: 'Stage failure rates' })}</h3>
          {Object.entries(data?.stageFailureRates ?? {}).length === 0 && (
            <div className="text-sm text-text-secondary">No failures recorded.</div>
          )}
          {Object.entries(data?.stageFailureRates ?? {}).map(([stage, rate]) => (
            <div key={stage} className="flex items-center justify-between border-b border-border-button py-2 text-sm last:border-b-0">
              <span className="text-text-secondary">{stage}</span>
              <span className="font-mono">{formatRate(rate)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-8 flex flex-wrap gap-3">
        <Link
          to={Routes.CsInterviewAdminSessions}
          className="rounded-md border border-border-button bg-bg-card px-4 py-2 text-sm hover:bg-bg-base"
        >
          {t('csInterview.admin.sessionAuditNav', { defaultValue: 'Session audit' })}
        </Link>
        <Link
          to={Routes.CsInterviewAdminFeedback}
          className="rounded-md border border-border-button bg-bg-card px-4 py-2 text-sm hover:bg-bg-base"
        >
          {t('csInterview.admin.feedbackNav', { defaultValue: 'Feedback & appeals' })}
        </Link>
      </div>
    </InterviewShell>
  );
}
