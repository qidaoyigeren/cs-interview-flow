import { useInterviewAdminCalibration } from '@/hooks/use-cs-interview-request';
import { InterviewShell, PageHeading } from '@/pages/cs-interview/components';
import { useTranslation } from 'react-i18next';

const MetricLabels: Record<string, string> = {
  agentHumanExactRatio: 'Agent/human exact agreement',
  agentHumanWithinOneRatio: 'Agent/human within-one agreement',
  weightedCohensKappa: 'Weighted Cohen’s kappa',
  macroF1: 'Macro F1 (score classes)',
  lowConfidenceAccuracy: 'Low-confidence sample accuracy',
  followupReasonableRatio: 'Follow-up reasonable ratio',
  anchorCoverageRatio: 'Must-have anchor coverage',
  anchorGroupStability: 'Anchor-group repeated-measures stability',
  reviewerInterRaterKappa: 'Inter-rater kappa (reviewer pairs)',
};

export default function AdminCalibration() {
  const { t } = useTranslation();
  const { data, isPending, error } = useInterviewAdminCalibration();

  if (error) {
    return (
      <InterviewShell>
        <div className="p-8 text-state-error">
          {t('csInterview.admin.unauthorized', {
            defaultValue: 'Administrator access required.',
          })}
        </div>
      </InterviewShell>
    );
  }

  const fixture = data?.fixture;
  return (
    <InterviewShell>
      <PageHeading
        eyebrow="ops console"
        title={t('csInterview.admin.calibrationTitle', {
          defaultValue: 'Rubric calibration',
        })}
        description={t('csInterview.admin.calibrationDescription', {
          defaultValue:
            'Agent-vs-human agreement over annotated cases. Metrics with too few samples are reported insufficient, never as a fabricated percentage.',
        })}
      />
      {isPending && <div className="p-8 text-text-secondary">Loading…</div>}
      {data?.fixtureMetadata && (
        <div className="mb-6 border border-state-warning/50 bg-state-warning/5 p-4 text-sm text-text-secondary">
          <span className="mr-2 font-mono text-xs text-state-warning">{data.fixtureMetadata.reviewStatus}</span>
          {data.fixtureMetadata.description}
        </div>
      )}
      {data && !fixture && (
        <div className="rounded-lg border border-dashed border-border-default p-8 text-center text-sm text-text-secondary">
          No calibration fixture loaded.
        </div>
      )}
      {fixture && (
        <div className="mb-6 grid gap-px overflow-hidden border border-border-button bg-border-button sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(fixture.metrics).map(([name, value]) => {
            const insufficient = Boolean(fixture.insufficient[name]);
            const sampleKey: Record<string, string> = {
              agentHumanExactRatio: 'agentHumanPairs',
              agentHumanWithinOneRatio: 'agentHumanPairs',
              weightedCohensKappa: 'agentHumanPairs',
              macroF1: 'agentHumanPairs',
              lowConfidenceAccuracy: 'lowConfidenceCases',
              followupReasonableRatio: 'followupCases',
              anchorCoverageRatio: 'anchorMustHave',
              anchorGroupStability: 'anchorPairs',
              reviewerInterRaterKappa: 'reviewerPairs',
            };
            const sample = fixture.sampleCounts[sampleKey[name] ?? 'cases'] ?? 0;
            return (
              <div key={name} className="bg-bg-base p-5">
                <div className="mb-3 text-xs text-text-secondary">
                  {MetricLabels[name] ?? name}
                  {insufficient && (
                    <span className="ml-2 rounded-full border border-state-warning px-2 py-0.5 font-mono text-[10px] text-state-warning">
                      insufficient sample
                    </span>
                  )}
                </div>
                <div className="text-2xl font-semibold">{typeof value === 'number' ? value.toFixed(3) : String(value)}</div>
                <div className="mt-1 font-mono text-[10px] text-text-secondary">n = {sample}</div>
              </div>
            );
          })}
        </div>
      )}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        {fixture && (
          <section className="rounded-lg border border-border-button p-5">
            <h2 className="mb-3 text-sm font-medium">Confusion matrix (rows = human adjudicated, cols = agent)</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead>
                  <tr className="border-b border-border-button">
                    <th className="p-2" />
                    {[0, 1, 2, 3, 4].map((col) => (
                      <th key={col} className="p-2 text-right">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[0, 1, 2, 3, 4].map((row) => (
                    <tr key={row} className="border-b border-border-button last:border-0">
                      <td className="p-2 font-semibold">{row}</td>
                      {[0, 1, 2, 3, 4].map((col) => (
                        <td key={col} className="p-2 text-right text-text-secondary">
                          {fixture.confusionMatrix[String(row)]?.[String(col)] ?? 0}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 font-mono text-[10px] text-text-secondary">
              rubric {fixture.versions.rubricVersion || '—'} · model {fixture.versions.modelVersion || '—'} · prompt{' '}
              {fixture.versions.promptVersion || '—'}
            </div>
          </section>
        )}
        {data?.annotationCases && data.annotationCases.length > 0 && (
          <section className="rounded-lg border border-border-button p-5">
            <h2 className="mb-3 text-sm font-medium">
              Annotation cases ({data.annotationCaseCount})
            </h2>
            <div className="divide-y divide-border-button">
              {data.annotationCases.slice(0, 20).map((item) => (
                <div key={item.caseId} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                  <span className="font-mono text-xs text-accent-primary">{item.caseId}</span>
                  <span className="text-text-secondary">{item.competencyId}</span>
                  <span className="font-mono text-xs">
                    {item.adjudicatedScore == null ? '—' : `${item.adjudicatedScore}/4`}
                  </span>
                  <span className="ml-auto font-mono text-[10px] text-text-secondary">
                    {item.reviewerCount} reviewers · {item.status}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </InterviewShell>
  );
}
