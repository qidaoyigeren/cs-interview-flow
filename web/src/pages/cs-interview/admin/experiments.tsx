import {
  CsInterviewKeys,
  useInterviewAdminExperiments,
} from '@/hooks/use-cs-interview-request';
import { InterviewShell, PageHeading } from '@/pages/cs-interview/components';
import csInterviewService from '@/services/cs-interview-service';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';

export default function Experiments() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isPending, error } = useInterviewAdminExperiments();
  const [name, setName] = useState('prompt-v2-production-scenario');
  const [traffic, setTraffic] = useState(10);

  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: CsInterviewKeys.adminExperiments(),
    });
  const createExperiment = useMutation({
    mutationFn: async () =>
      csInterviewService.createExperiment({
        name,
        status: 'gray',
        traffic_percentage: traffic,
        control_variant: {
          variant_id: 'control',
          prompt_version: 'cs-interview-v1',
          planner_version: 'cs-interview-planner-v1',
        },
        candidate_variants: [
          {
            variant_id: 'prompt-v2',
            prompt_version: 'cs-interview-v2',
            planner_version: 'cs-interview-planner-v1',
            temperatures: { generate_question: 0.1, judge: 0 },
            feature_flags: { semantic_dedup: true },
          },
        ],
        guardrail_metrics: [
          {
            metric: 'answer_request_failure_rate',
            operator: '>=',
            target: 0.05,
          },
        ],
      }),
    onSuccess: refresh,
  });
  const stopExperiment = useMutation({
    mutationFn: async (id: string) =>
      csInterviewService.stopExperiment({ id }),
    onSuccess: refresh,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) createExperiment.mutate();
  };

  if (error) {
    return (
      <InterviewShell>
        <div className="p-8 text-state-error">
          {t('csInterview.admin.unauthorized')}
        </div>
      </InterviewShell>
    );
  }

  return (
    <InterviewShell>
      <PageHeading
        eyebrow="ops console"
        title={t('csInterview.admin.experimentsTitle')}
        description={t('csInterview.admin.experimentsDescription')}
      />

      <form
        onSubmit={submit}
        className="mb-8 grid gap-4 rounded-lg border border-border-button bg-bg-card p-4 md:grid-cols-[1fr_160px_auto] md:items-end"
      >
        <label className="text-xs text-text-secondary">
          Experiment name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-2 w-full rounded-md border border-border-button bg-bg-base px-3 py-2 text-sm text-text-primary"
          />
        </label>
        <label className="text-xs text-text-secondary">
          Candidate traffic %
          <input
            type="number"
            min={0}
            max={100}
            value={traffic}
            onChange={(event) => setTraffic(Number(event.target.value))}
            className="mt-2 w-full rounded-md border border-border-button bg-bg-base px-3 py-2 text-sm text-text-primary"
          />
        </label>
        <button
          type="submit"
          disabled={createExperiment.isPending || !name.trim()}
          className="rounded-md bg-accent-primary px-4 py-2 text-sm text-white disabled:opacity-40"
        >
          Start prompt v2 gray release
        </button>
      </form>

      <div className="overflow-x-auto rounded-lg border border-border-button">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="bg-bg-card text-xs uppercase tracking-wide text-text-secondary">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Traffic</th>
              <th className="px-4 py-3">Owner</th>
              <th className="px-4 py-3">Action</th>
            </tr>
          </thead>
          <tbody>
            {isPending && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-text-secondary">
                  Loading…
                </td>
              </tr>
            )}
            {(data?.items ?? []).map((row) => (
              <tr key={row.id} className="border-t border-border-button">
                <td className="px-4 py-3 font-medium">{row.name}</td>
                <td className="px-4 py-3 font-mono text-xs">{row.status}</td>
                <td className="px-4 py-3">{row.trafficPercentage}%</td>
                <td className="px-4 py-3 font-mono text-xs">{row.createdBy ?? '—'}</td>
                <td className="px-4 py-3">
                  {row.status === 'gray' && (
                    <button
                      type="button"
                      onClick={() => stopExperiment.mutate(row.id)}
                      disabled={stopExperiment.isPending}
                      className="rounded-md border border-border-button px-3 py-1 text-xs hover:bg-bg-base disabled:opacity-40"
                    >
                      Stop
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </InterviewShell>
  );
}
