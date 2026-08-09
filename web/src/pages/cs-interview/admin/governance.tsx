import {
  useInterviewAdminQuestions,
} from '@/hooks/use-cs-interview-request';
import csInterviewService, { camelizeInterviewData } from '@/services/cs-interview-service';
import { InterviewShell, PageHeading } from '@/pages/cs-interview/components';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

type GovernanceAction = {
  resourceType: 'question' | 'evidence' | 'session';
  resourceId: string;
  action: 'mark_bad' | 'take_down' | 'review';
  comment: string;
};

export default function Governance() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isPending } = useInterviewAdminQuestions();
  const [comment, setComment] = useState('');
  const [target, setTarget] = useState<GovernanceAction | null>(null);

  const reviewMutation = useMutation<Record<string, any>, Error, GovernanceAction>({
    mutationFn: async (payload) =>
      camelizeInterviewData((await csInterviewService.adminReview(payload)).data.data),
    onSuccess: () => {
      setTarget(null);
      setComment('');
      queryClient.invalidateQueries();
    },
  });

  const rows = (data ?? []) as Array<{ questionId: string; topic: string; attempts: number; failures: number; latestScore?: number }>;

  return (
    <InterviewShell>
      <PageHeading
        eyebrow="ops console"
        title={t('csInterview.admin.governanceTitle', { defaultValue: 'Question & evidence governance' })}
        description={t('csInterview.admin.governanceDescription', {
          defaultValue: 'High-failure questions, bad-question marking and evidence take-down.',
        })}
      />
      <div className="overflow-x-auto rounded-lg border border-border-button">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="bg-bg-card text-xs uppercase tracking-wide text-text-secondary">
            <tr>
              <th className="px-4 py-3">Question</th>
              <th className="px-4 py-3">Topic</th>
              <th className="px-4 py-3">Attempts</th>
              <th className="px-4 py-3">Failures</th>
              <th className="px-4 py-3">Latest</th>
              <th className="px-4 py-3">Action</th>
            </tr>
          </thead>
          <tbody>
            {isPending && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-text-secondary">Loading…</td></tr>
            )}
            {rows.map((row) => (
              <tr key={row.questionId} className="border-t border-border-button">
                <td className="px-4 py-3 font-mono text-xs">{row.questionId}</td>
                <td className="px-4 py-3">{row.topic}</td>
                <td className="px-4 py-3">{row.attempts}</td>
                <td className="px-4 py-3 text-state-error">{row.failures}</td>
                <td className="px-4 py-3">{row.latestScore ?? '—'}</td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => setTarget({ resourceType: 'question', resourceId: row.questionId, action: 'mark_bad', comment })}
                    className="rounded-md border border-border-button px-2 py-1 text-xs hover:bg-bg-base"
                  >
                    mark bad
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {target && (
        <div className="mt-6 rounded-lg border border-border-button p-4">
          <h3 className="mb-3 text-sm font-semibold">
            {target.action} · {target.resourceType} · {target.resourceId}
          </h3>
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder={t('csInterview.admin.reviewComment', { defaultValue: 'Review comment' })}
            className="w-full rounded-md border border-border-button bg-bg-base p-3 text-sm outline-none focus:border-accent-primary"
            rows={3}
          />
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => reviewMutation.mutate({ ...target, comment })}
              disabled={reviewMutation.isPending}
              className="rounded-md bg-accent-primary px-4 py-2 text-sm text-white disabled:opacity-40"
            >
              Submit
            </button>
            <button
              type="button"
              onClick={() => setTarget(null)}
              className="rounded-md border border-border-button px-4 py-2 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </InterviewShell>
  );
}
