import { useInterviewAdminFeedback } from '@/hooks/use-cs-interview-request';
import { InterviewShell, PageHeading } from '@/pages/cs-interview/components';
import { useTranslation } from 'react-i18next';

const KindLabels: Record<string, string> = {
  irrelevant_question: 'irrelevant question',
  unclear_wording: 'unclear wording',
  unfair_scoring: 'unfair scoring',
  stale_evidence: 'stale evidence',
  technical_error: 'technical error',
  privacy_issue: 'privacy issue',
};

export default function AdminFeedback() {
  const { t } = useTranslation();
  const { data, isPending, error } = useInterviewAdminFeedback();

  if (error) {
    return (
      <InterviewShell>
        <div className="p-8 text-state-error">
          {t('csInterview.admin.unauthorized', { defaultValue: 'Administrator access required.' })}
        </div>
      </InterviewShell>
    );
  }

  return (
    <InterviewShell>
      <PageHeading
        eyebrow="ops console"
        title={t('csInterview.admin.feedbackTitle', { defaultValue: 'User feedback & appeals' })}
        description={t('csInterview.admin.feedbackDescription', {
          defaultValue: 'Feedback tied to session/round/question/evidence and the exact model, prompt and planner versions.',
        })}
      />
      {isPending && <div className="p-8 text-text-secondary">Loading…</div>}
      <div className="space-y-3">
        {(data ?? []).length === 0 && !isPending && (
          <div className="rounded-lg border border-dashed border-border-default p-8 text-center text-sm text-text-secondary">
            No feedback yet.
          </div>
        )}
        {(data ?? []).map((item) => (
          <div key={item.id} className="rounded-lg border border-border-button p-4">
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <span className="rounded-full border border-border-button px-2 py-0.5 font-mono">
                {KindLabels[item.kind] ?? item.kind}
              </span>
              <span className="font-mono text-accent-primary">{item.sessionId}</span>
              {item.roundId && <span className="text-text-secondary">round {item.roundId}</span>}
              <span className="text-text-secondary">{item.createdAt}</span>
            </div>
            <p className="mt-2 text-sm leading-6">{item.message}</p>
            <div className="mt-2 font-mono text-[10px] text-text-secondary">
              prompt {item.promptVersion ?? '—'} · planner {item.plannerVersion ?? '—'} · model {item.model ?? '—'}
            </div>
          </div>
        ))}
      </div>
    </InterviewShell>
  );
}
