import { Button } from '@/components/ui/button';
import {
  useInterviewReport,
  useInterviewSession,
} from '@/hooks/use-cs-interview-request';
import { Routes } from '@/routes';
import {
  ArrowRight,
  BadgeCheck,
  BarChart3,
  CheckCircle2,
  ClipboardList,
  Loader2,
  RotateCcw,
  Sparkles,
  Target,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import { useParams } from 'react-router';
import {
  InterviewShell,
  PageHeading,
  ScoreMark,
  SectionTitle,
} from './components';

const scoreWidth = (score: number) => `${Math.max(3, (score / 4) * 100)}%`;

export default function InterviewReportPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const reportQuery = useInterviewReport(id);
  const sessionQuery = useInterviewSession(id);

  if (reportQuery.isLoading || sessionQuery.isLoading) {
    return (
      <InterviewShell>
        <div className="flex h-64 items-center justify-center text-text-secondary">
          <Loader2 className="mr-2 size-4 animate-spin" />
          {t('csInterview.report.loading')}
        </div>
      </InterviewShell>
    );
  }

  const report = reportQuery.data;
  const session = sessionQuery.data;
  if (reportQuery.isError || sessionQuery.isError || !report || !session) {
    return (
      <InterviewShell>
        <div className="border border-state-error bg-state-error-5 p-6 text-state-error">
          {t('csInterview.report.loadError')}
        </div>
      </InterviewShell>
    );
  }

  return (
    <InterviewShell>
      <PageHeading
        eyebrow={t('csInterview.report.eyebrow')}
        title={t('csInterview.report.title')}
        description={t('csInterview.report.description')}
        action={
          <Button asLink to={Routes.CsInterviewConfigure} size="lg">
            {t('csInterview.report.nextInterview')}
            <ArrowRight />
          </Button>
        }
      />

      <section className="mb-12 grid gap-px overflow-hidden border border-border-button bg-border-button md:grid-cols-[1.1fr_0.9fr_0.9fr_0.9fr]">
        <div className="bg-bg-base p-7">
          <div className="mb-5 font-mono text-[10px] uppercase tracking-widest text-text-secondary">
            {t('csInterview.report.overall')}
          </div>
          <ScoreMark value={report.overallScore} />
          <div
            className="mt-3 text-lg tracking-[0.18em] text-state-warning"
            aria-label={t('csInterview.report.starRating')}
          >
            {'★'.repeat(Math.round(report.starRating))}
            <span className="text-border-button">
              {'★'.repeat(5 - Math.round(report.starRating))}
            </span>
          </div>
        </div>
        <Metric
          label={t('csInterview.report.initialAverage')}
          value={report.metrics.initialAnswerAverage}
        />
        <Metric
          label={t('csInterview.report.followupAverage')}
          value={report.metrics.postFollowupAverage}
        />
        <div className="bg-bg-base p-7">
          <div className="mb-5 font-mono text-[10px] uppercase tracking-widest text-text-secondary">
            {t('csInterview.report.followups')}
          </div>
          <div className="text-3xl font-semibold">
            {report.metrics.followupCount}
          </div>
          <div className="mt-2 text-xs text-text-secondary">
            {t('csInterview.report.questions', {
              count: report.metrics.questionCount,
            })}
          </div>
        </div>
      </section>

      <section className="mb-12">
        <SectionTitle icon={BadgeCheck}>JD 能力验证矩阵</SectionTitle>
        <p className="mb-4 text-xs leading-5 text-text-secondary">
          简历声明、面试验证与未覆盖项分别展示；分数由实际轮次确定性聚合。
        </p>
        <div className="overflow-x-auto border border-border-button">
          <table className="min-w-[1100px] w-full text-left text-sm">
            <thead className="border-b border-border-button bg-bg-card font-mono text-[10px] uppercase text-text-secondary">
              <tr>
                <th className="p-3">JD 要求</th>
                <th className="p-3">权重</th>
                <th className="p-3">简历声明</th>
                <th className="p-3">实际测试题</th>
                <th className="p-3">得分</th>
                <th className="p-3">验证状态</th>
                <th className="p-3">支持证据</th>
                <th className="p-3">改进建议</th>
              </tr>
            </thead>
            <tbody>
              {(report.jdVerificationMatrix ?? []).map((item) => (
                <tr key={item.requirementId} className="border-b border-border-button align-top last:border-0">
                  <td className="p-3 font-medium">
                    {item.requirementText}
                    {item.unmapped && <span className="ml-2 text-xs text-state-warning">未映射</span>}
                  </td>
                  <td className="p-3 font-mono">{item.weight.toFixed(3)}</td>
                  <td className="p-3">{item.resumeClaimStatus}</td>
                  <td className="p-3">{item.actualQuestions.map((question) => question.questionText).join('；') || '未覆盖'}</td>
                  <td className="p-3 font-mono">{item.score == null ? '—' : `${item.score.toFixed(2)}/4`}</td>
                  <td className="p-3">{item.verificationStatus}</td>
                  <td className="p-3">
                    {item.supportEvidence
                      .map((evidence) => {
                        const source = evidence.questionId || evidence.roundId || 'evidence';
                        const ids = evidence.evidenceIds.join(', ');
                        return ids ? `${source}: ${ids}` : source;
                      })
                      .join('；') || '—'}
                  </td>
                  <td className="p-3">{item.improvementRecommendation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {report.competencyVerification && report.competencyVerification.length > 0 && (
        <section className="mb-12">
          <SectionTitle icon={Target}>能力验证证据轨道</SectionTitle>
          <p className="mb-4 text-xs leading-5 text-text-secondary">
            JD 要求 → 简历声明 → 锚点题 → 自适应追问 → 回答证据 → 能力结论。未覆盖能力不显示为低分。
          </p>
          <div className="space-y-4">
            {report.competencyVerification.map((item) => (
              <details
                key={item.competencyId}
                className="rounded-lg border border-border-button"
              >
                <summary className="flex cursor-pointer list-none flex-wrap items-center gap-3 p-4">
                  <span className="font-mono text-xs text-accent-primary">
                    {item.competencyId}
                  </span>
                  <span className="text-sm font-medium">{item.name}</span>
                  <CompetencyStatusPill status={item.status} />
                  <span className="ml-auto font-mono text-xs text-text-secondary">
                    {item.score == null ? '未考' : `${item.score.toFixed(1)}/4`}
                  </span>
                </summary>
                <div className="border-t border-border-button px-4 py-4">
                  <p className="mb-3 text-sm leading-6">{item.conclusion}</p>
                  <div className="space-y-2">
                    {item.evidenceTrack.map((evidence, index) => (
                      <div
                        key={`${item.competencyId}-${index}`}
                        className="grid grid-cols-[120px_minmax(0,1fr)] gap-3 text-xs leading-6"
                      >
                        <span className="font-mono uppercase text-text-secondary">
                          {evidence.kind}
                        </span>
                        <div>
                          <span className="text-text-primary">
                            {evidence.text || evidence.questionText}
                          </span>
                          {evidence.spans && evidence.spans.length > 0 && (
                            <span className="ml-2 text-text-secondary">
                              「{evidence.spans.map((span) => span.text).join('；')}」
                            </span>
                          )}
                          {evidence.score != null && (
                            <span className="ml-2 font-mono text-text-secondary">
                              {evidence.score}/4
                            </span>
                          )}
                          {evidence.lowConfidence && (
                            <span className="ml-2 rounded-full border border-state-warning px-2 py-0.5 font-mono text-[10px] text-state-warning">
                              低置信
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </details>
            ))}
          </div>
        </section>
      )}

      {report.projectClaimVerification &&
        report.projectClaimVerification.length > 0 && (
          <section className="mb-12">
            <SectionTitle icon={Target}>项目声明验真矩阵</SectionTitle>
            <p className="mb-4 text-xs leading-5 text-text-secondary">
              技术能力得分（相关题目平均分）与项目声明可信度分开展示；「已验证」仅表示候选人以项目相关证据、达标得分与足够置信度演示了该声明，不代表回答技术分高就等于简历真实。
            </p>
            <div className="overflow-x-auto border border-border-button">
              <table className="min-w-[1200px] w-full text-left text-sm">
                <thead className="border-b border-border-button bg-bg-card font-mono text-[10px] uppercase text-text-secondary">
                  <tr>
                    <th className="p-3">项目</th>
                    <th className="p-3">简历声明</th>
                    <th className="p-3">深挖维度</th>
                    <th className="p-3">验证状态</th>
                    <th className="p-3">回答证据</th>
                    <th className="p-3">相关问题</th>
                    <th className="p-3">技术能力得分</th>
                  </tr>
                </thead>
                <tbody>
                  {report.projectClaimVerification.map((item) => (
                    <tr
                      key={item.claimId}
                      className="border-b border-border-button align-top last:border-0"
                    >
                      <td className="p-3 font-medium">{item.projectName}</td>
                      <td className="p-3">
                        {item.claimText}
                        <div className="mt-1 font-mono text-[10px] text-text-secondary">
                          {item.claimType}
                        </div>
                      </td>
                      <td className="p-3">
                        {item.dimensions.map((entry) => (
                          <div
                            key={entry.dimension}
                            className="mb-1 font-mono text-xs"
                          >
                            {entry.dimension}
                            <span className="ml-2 text-text-secondary">
                              ×{entry.attemptCount}
                            </span>
                          </div>
                        ))}
                      </td>
                      <td className="p-3">
                        <ProjectClaimStatusPill
                          status={item.verificationStatus}
                        />
                      </td>
                      <td className="p-3 text-xs leading-5">
                        {item.dimensions
                          .flatMap((entry) =>
                            entry.answeredEvidence.map(
                              (evidence) => evidence.evidenceSpan,
                            ),
                          )
                          .filter((span, index, all) => all.indexOf(span) === index)
                          .join('；') || '—'}
                      </td>
                      <td className="p-3 font-mono text-xs text-text-secondary">
                        {item.dimensions
                          .flatMap((entry) => entry.relatedQuestionIds)
                          .filter((id, index, all) => all.indexOf(id) === index)
                          .join(', ') || '—'}
                      </td>
                      <td className="p-3 font-mono">
                        {item.score == null
                          ? '—'
                          : `${item.score.toFixed(2)}/4`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-12">
          <section>
            <SectionTitle icon={BarChart3}>
              {t('csInterview.report.ability')}
            </SectionTitle>
            <div className="space-y-4 border-y border-border-button py-5">
              {Object.entries(report.abilityScores).map(([topic, score]) => (
                <div
                  key={topic}
                  className="grid grid-cols-[minmax(120px,1fr)_2fr_44px] items-center gap-4"
                >
                  <span className="truncate text-sm">{topic}</span>
                  <div className="h-1.5 overflow-hidden rounded-full bg-bg-card">
                    <div
                      className="h-full bg-text-primary"
                      style={{ width: scoreWidth(score) }}
                    />
                  </div>
                  <span className="text-right font-mono text-xs text-text-secondary">
                    {score.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-5 grid gap-px bg-border-button sm:grid-cols-3">
              <DimensionScores
                title={t('csInterview.report.byDifficulty')}
                values={report.metrics.difficultyScores}
              />
              <DimensionScores
                title={t('csInterview.report.byCategory')}
                values={report.metrics.categoryScores}
              />
              <DimensionScores
                title={t('csInterview.report.byQuestionType')}
                values={report.metrics.questionTypeScores}
              />
            </div>
          </section>

          <section>
            <SectionTitle icon={ClipboardList}>
              {t('csInterview.report.rounds')}
            </SectionTitle>
            <div className="divide-y divide-border-button border-y border-border-button">
              {(session.rounds || []).map((round) => (
                <details key={round.id} className="group py-5">
                  <summary className="grid cursor-pointer list-none gap-3 sm:grid-cols-[48px_minmax(0,1fr)_auto] sm:items-center">
                    <span className="font-mono text-xs text-text-secondary">
                      Q{round.sequence.toString().padStart(2, '0')}
                    </span>
                    <div>
                      <div className="line-clamp-2 text-sm font-medium leading-6">
                        {round.questionText}
                      </div>
                      <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-text-secondary">
                        {round.category} · {round.topic} · {round.difficulty}
                      </div>
                    </div>
                    <span className="font-mono text-sm">
                      {round.score?.toFixed(1) ?? '—'} / 4
                    </span>
                  </summary>
                  <div className="mt-5 space-y-5 border-l border-border-default pl-5 sm:ml-12">
                    {round.candidateAnswers.map((answer, index) => (
                      <div key={`${round.id}-${index}`}>
                        <div className="mb-1 text-xs font-medium text-text-secondary">
                          {answer.kind === 'initial'
                            ? t('csInterview.report.initialAnswer')
                            : t('csInterview.report.followupAnswer', {
                                number: index,
                              })}
                        </div>
                        <p className="whitespace-pre-wrap text-sm leading-6">
                          {answer.answer}
                        </p>
                      </div>
                    ))}
                    {round.feedback && (
                      <div className="bg-bg-card p-4 text-sm leading-6">
                        <div className="mb-2 text-xs font-medium text-text-secondary">
                          {t('csInterview.report.feedback')}
                        </div>
                        {round.feedback}
                      </div>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </section>

          <section>
            <SectionTitle icon={Sparkles}>
              {t('csInterview.report.summary')}
            </SectionTitle>
            <div className="prose max-w-none border-l-2 border-text-primary pl-6 text-text-primary dark:prose-invert">
              <ReactMarkdown>{report.reportMarkdown}</ReactMarkdown>
            </div>
          </section>
        </div>

        <aside className="space-y-7">
          <ReportList
            icon={CheckCircle2}
            title={t('csInterview.report.strengths')}
            items={report.strengths.map(
              (item) => `${item.topic} · ${item.score.toFixed(2)}`,
            )}
          />
          <ReportList
            icon={Target}
            title={t('csInterview.report.weaknesses')}
            items={report.weaknesses.map(
              (item) => `${item.topic} · P${item.priority}`,
            )}
          />
          <section className="border border-border-button p-6">
            <SectionTitle icon={RotateCcw}>
              {t('csInterview.report.trainingPlan')}
            </SectionTitle>
            <ol className="space-y-5">
              {report.trainingPlan.map((item) => (
                <li
                  key={item.order}
                  className="grid grid-cols-[28px_1fr] gap-3"
                >
                  <span className="flex size-7 items-center justify-center rounded-full border border-border-default font-mono text-xs">
                    {item.order}
                  </span>
                  <div>
                    <div className="text-sm font-medium">{item.topic}</div>
                    <p className="mt-1 text-xs leading-5 text-text-secondary">
                      {item.action}
                    </p>
                    <p className="mt-2 text-xs leading-5">
                      {item.successCriteria}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
          {report.skillVerification && report.skillVerification.length > 0 && (
            <section className="border border-border-button p-6">
              <SectionTitle icon={BadgeCheck}>
                {t('csInterview.report.skillVerification')}
              </SectionTitle>
              <p className="mb-4 text-xs leading-5 text-text-secondary">
                {t('csInterview.report.skillVerificationDescription')}
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-border-button font-mono text-[11px] uppercase tracking-wide text-text-secondary">
                    <tr>
                      <th className="py-2 pr-4">{t('csInterview.resumeDetail.claimedSkills')}</th>
                      <th className="py-2 pr-4">{t('csInterview.resumeDetail.claimedLevel')}</th>
                      <th className="py-2 pr-4">{t('csInterview.report.skillStatus.status')}</th>
                      <th className="py-2 pr-4">{t('csInterview.report.testedRounds')}</th>
                      <th className="py-2">{t('csInterview.report.avgScore')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.skillVerification.map((item) => (
                      <tr key={item.skill} className="border-b border-border-button last:border-0">
                        <td className="py-2.5 pr-4 font-medium">{item.skill}</td>
                        <td className="py-2.5 pr-4">{item.claimedLevel}</td>
                        <td className="py-2.5 pr-4">
                          <span className="font-mono text-[11px] uppercase">
                            {t(`csInterview.report.skillStatus.${item.status}`)}
                          </span>
                        </td>
                        <td className="py-2.5 pr-4">{item.testedRoundCount}</td>
                        <td className="py-2.5">
                          {item.avgScore != null ? item.avgScore.toFixed(1) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <section className="border border-border-button bg-bg-card p-6">
            <div className="font-mono text-[10px] uppercase tracking-wider text-text-secondary">
              {t('csInterview.report.recommendation')}
            </div>
            <div className="mt-3 text-sm font-medium">
              {report.metrics.recommendedRole}
            </div>
            <div className="mt-1 text-xs text-text-secondary">
              {report.metrics.recommendedDifficulty}
            </div>
          </section>
        </aside>
      </div>
    </InterviewShell>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-bg-base p-7">
      <div className="mb-5 font-mono text-[10px] uppercase tracking-widest text-text-secondary">
        {label}
      </div>
      <ScoreMark value={value} />
    </div>
  );
}

function DimensionScores({
  title,
  values,
}: {
  title: string;
  values: Record<string, number>;
}) {
  return (
    <div className="bg-bg-base p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-wider text-text-secondary">
        {title}
      </div>
      <div className="space-y-2">
        {Object.entries(values).map(([name, score]) => (
          <div key={name} className="flex justify-between gap-3 text-xs">
            <span>{name}</span>
            <span className="font-mono text-text-secondary">
              {score.toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const CompetencyStatusLabels: Record<string, string> = {
  verified: '已验证',
  partial: '部分验证',
  insufficient_evidence: '证据不足',
  contradiction: '存在矛盾',
  uncovered: '未覆盖',
};

const ProjectClaimStatusLabels: Record<string, string> = {
  verified: '已验证',
  partial: '部分验证',
  disputed: '存在差距',
  contradiction: '存在矛盾',
  low_confidence: '置信不足',
  untested: '未覆盖',
};

function ProjectClaimStatusPill({ status }: { status: string }) {
  const tone =
    status === 'verified'
      ? 'border-state-success text-state-success'
      : status === 'partial'
        ? 'border-state-warning text-state-warning'
        : status === 'contradiction' || status === 'disputed'
          ? 'border-state-error text-state-error'
          : 'border-border-button text-text-secondary';
  return (
    <span
      className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${tone}`}
    >
      {ProjectClaimStatusLabels[status] ?? status}
    </span>
  );
}

function CompetencyStatusPill({ status }: { status: string }) {
  const tone =
    status === 'verified'
      ? 'border-state-success text-state-success'
      : status === 'partial'
        ? 'border-state-warning text-state-warning'
        : status === 'contradiction'
          ? 'border-state-error text-state-error'
          : 'border-border-button text-text-secondary';
  return (
    <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${tone}`}>
      {CompetencyStatusLabels[status] ?? status}
    </span>
  );
}

function ReportList({
  icon: Icon,
  title,
  items,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  items: string[];
}) {
  return (
    <section className="border border-border-button p-6">
      <SectionTitle icon={Icon}>{title}</SectionTitle>
      <ul className="space-y-3 text-sm">
        {items.map((item) => (
          <li
            key={item}
            className="border-l border-border-default pl-3 leading-6"
          >
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}
