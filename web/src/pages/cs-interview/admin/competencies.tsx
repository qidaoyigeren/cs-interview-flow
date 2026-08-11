import { useInterviewAdminCompetencies } from '@/hooks/use-cs-interview-request';
import { InterviewShell, PageHeading } from '@/pages/cs-interview/components';
import { useTranslation } from 'react-i18next';

const StatusLabel: Record<string, string> = {
  anchored: 'anchor required before adaptive',
  adaptive_ok: 'adaptive allowed',
};

export default function AdminCompetencies() {
  const { t } = useTranslation();
  const { data, isPending, error } = useInterviewAdminCompetencies();

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

  return (
    <InterviewShell>
      <PageHeading
        eyebrow="ops console"
        title={t('csInterview.admin.competenciesTitle', {
          defaultValue: 'Competency & rubric versions',
        })}
        description={t('csInterview.admin.competenciesDescription', {
          defaultValue:
            'Per-role competency definitions, score anchors (0..4) and anchor question groups. Rubric snapshots are frozen per session.',
        })}
      />
      {isPending && <div className="p-8 text-text-secondary">Loading…</div>}
      {data && (
        <div className="mb-4 rounded-lg border border-border-button p-4 text-sm">
          <span className="font-mono text-accent-primary">{data.rubricVersion}</span>
          <span className="ml-3 text-text-secondary">
            · {data.anchorGroupCount} anchor groups
          </span>
        </div>
      )}
      {data?.levelPolicies && (
        <div className="mb-6 grid gap-px overflow-hidden border border-border-button bg-border-button sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(data.levelPolicies).map(([level, policy]) => (
            <div key={level} className="bg-bg-base p-4 text-sm">
              <div className="mb-2 font-mono text-xs uppercase text-accent-primary">{level}</div>
              <div className="font-medium">required score {policy.requiredScore}/4</div>
              <div className="mt-1 text-xs text-text-secondary">
                {policy.minimumHighConfidenceEvidence} high-confidence evidence · {policy.defaultDifficulty}
              </div>
              <div className="mt-2 text-xs text-text-secondary">{policy.expectation}</div>
            </div>
          ))}
        </div>
      )}
      <div className="space-y-6">
        {(data?.roles ?? []).length === 0 && !isPending && (
          <div className="rounded-lg border border-dashed border-border-default p-8 text-center text-sm text-text-secondary">
            No competency catalog available.
          </div>
        )}
        {Object.entries(data?.roles ?? {}).map(([role, competencies]) => (
          <section key={role} className="rounded-lg border border-border-button">
            <div className="border-b border-border-button bg-bg-card px-4 py-3 font-mono text-xs uppercase tracking-widest text-text-secondary">
              {role}
            </div>
            <div className="divide-y divide-border-button">
              {competencies.map((item) => (
                <div key={item.competencyId} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                  <span className="font-mono text-accent-primary">{item.competencyId}</span>
                  <span className="font-medium">{item.name}</span>
                  {item.mustHave && (
                    <span className="rounded-full border border-state-warning px-2 py-0.5 font-mono text-[10px] text-state-warning">
                      must-have
                    </span>
                  )}
                  <span className="font-mono text-[10px] text-text-secondary">
                    w {item.weight.toFixed(2)} · anchors {item.scoreAnchorLevels.join('-')}
                  </span>
                  <span className="ml-auto text-[10px] text-text-secondary">
                    {StatusLabel[item.anchorQuestionPolicy] ?? item.anchorQuestionPolicy}
                  </span>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
      {data?.anchorGroups && data.anchorGroups.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-3 text-sm font-medium">Anchor question groups</h2>
          <div className="overflow-x-auto border border-border-button">
            <table className="w-full min-w-[700px] text-left text-sm">
              <thead className="border-b border-border-button bg-bg-card font-mono text-[10px] uppercase text-text-secondary">
                <tr>
                  <th className="p-3">Anchor group</th>
                  <th className="p-3">Competency</th>
                  <th className="p-3">Difficulty</th>
                  <th className="p-3">Question ids</th>
                </tr>
              </thead>
              <tbody>
                {data.anchorGroups.map((group) => (
                  <tr key={group.anchorGroupId} className="border-b border-border-button last:border-0">
                    <td className="p-3 font-mono">{group.anchorGroupId}</td>
                    <td className="p-3">{group.competencyId}</td>
                    <td className="p-3">{group.difficulty}</td>
                    <td className="p-3 font-mono text-xs text-text-secondary">
                      {group.questionIds.length ? group.questionIds.join(', ') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </InterviewShell>
  );
}
