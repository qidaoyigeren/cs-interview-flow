import {
  useInterviewAdminSessionAudit,
} from '@/hooks/use-cs-interview-request';
import csInterviewService, { camelizeInterviewData } from '@/services/cs-interview-service';
import { InterviewReplayResult } from '@/interfaces/database/cs-interview';
import { InterviewShell, PageHeading, StatusPill } from '@/pages/cs-interview/components';
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';

function ReplayBadge({ status }: { status?: string }) {
  const color =
    status === 'deterministic'
      ? 'border-state-success bg-state-success-5 text-state-success'
      : status === 'changed'
        ? 'border-state-error bg-state-error-5 text-state-error'
        : 'border-border-button text-text-secondary';
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wide ${color}`}>
      {status ?? 'pending'}
    </span>
  );
}

export default function SessionDetail() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const { data, isPending } = useInterviewAdminSessionAudit(id);
  const [replay, setReplay] = useState<InterviewReplayResult | null>(null);

  const replayMutation = useMutation<InterviewReplayResult, Error, string>({
    mutationFn: async (sessionId) =>
      camelizeInterviewData(
        (await csInterviewService.adminSessionReplay({ sessionId, plannerVersion: 'latest' })).data.data,
      ) as InterviewReplayResult,
    onSuccess: setReplay,
  });

  return (
    <InterviewShell>
      <PageHeading
        eyebrow="ops console"
        title={t('csInterview.admin.sessionDetailTitle', { defaultValue: 'Session audit detail' })}
        description={t('csInterview.admin.sessionDetailDescription', {
          defaultValue: 'Timeline, planner decisions and read-only replay comparison. Answers appear only as length+hash summaries.',
        })}
      />
      {isPending && <div className="p-8 text-text-secondary">Loading…</div>}
      {data && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <StatusPill status={data.status} />
            <span className="font-mono text-xs">planner {data.plannerVersion}</span>
            <span className="font-mono text-xs">prompt {data.promptVersion}</span>
            {data.failureCode && <span className="text-state-error">{data.failureCode}</span>}
            <button
              type="button"
              disabled={replayMutation.isPending}
              onClick={() => replayMutation.mutate(data.sessionId)}
              className="rounded-md border border-border-button bg-bg-card px-3 py-1 text-xs hover:bg-bg-base disabled:opacity-40"
            >
              {t('csInterview.admin.runReplay', { defaultValue: 'Run replay' })}
            </button>
            {replay && (
              <div className="flex items-center gap-3">
                <ReplayBadge status={replay.status} />
                <span className="font-mono text-xs">
                  {replay.deterministicCount}/{replay.totalCount} deterministic
                </span>
              </div>
            )}
          </div>

          <section>
            <h3 className="mb-2 text-sm font-semibold">{t('csInterview.admin.timeline', { defaultValue: 'Timeline' })}</h3>
            <div className="rounded-lg border border-border-button">
              {data.timeline.length === 0 && <div className="p-4 text-sm text-text-secondary">No trace events.</div>}
              {data.timeline.map((event, index) => (
                <div key={index} className="flex items-center justify-between border-b border-border-button px-4 py-2 text-xs last:border-b-0">
                  <span className="font-mono text-accent-primary">{event.eventType}</span>
                  <span className="text-text-secondary">{event.occurredAt}</span>
                  <span className={event.status === 'failed' ? 'text-state-error' : 'text-text-secondary'}>
                    {event.errorCode ?? event.status}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold">{t('csInterview.admin.plannerDecisions', { defaultValue: 'Planner decisions' })}</h3>
            {data.rounds.map((round) => (
              <div key={round.sequence} className="mb-3 rounded-lg border border-border-button p-4">
                <div className="flex flex-wrap items-center gap-3 text-xs text-text-secondary">
                  <span>round {round.sequence}</span>
                  <span>{round.topic}</span>
                  <span>{round.category}</span>
                  <span>score {round.score ?? '—'}</span>
                  <span className="font-mono">answer: {round.answerSummary}</span>
                </div>
                <div className="mt-3 space-y-1">
                  {round.plannerActions.map((action, index) => (
                    <div key={index} className="rounded-md bg-bg-base px-3 py-1.5 font-mono text-[11px] text-text-secondary">
                      {action.selectedAction} → {action.targetTopic ?? '—'} {action.reason ? `(${action.reason})` : ''}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </section>
        </div>
      )}
    </InterviewShell>
  );
}
