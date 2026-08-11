import {
  ArrowRight,
  ChevronRight,
  ListOrdered,
  Rocket,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
} from 'lucide-react';
import { useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge, Tag } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Loading } from '@/components/ui/feedback';
import { Panel, PanelBody, PanelHeader } from '@/components/ui/Panel';
import { TraceChain, type TraceLink } from '@/components/evidence/TraceChain';
import { AbilityBars } from '@/components/report/AbilityBars';
import { RadarChart } from '@/components/report/RadarChart';
import { useReport, useSession } from '@/hooks/use-cs-query';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/cn';
import type { EvidenceState, InterviewReport, InterviewRound, JDVerificationItem, SkillVerificationItem } from '@/lib/types';

const CATEGORY_LABEL: Record<string, string> = {
  baguwen: '八股题',
  interview_experience: '项目/场景题',
  leetcode: '算法题',
};

const DIFFICULTY_LABEL: Record<string, string> = {
  beginner: '初级',
  medium: '中级',
  advanced: '高级',
};

function scoreState(score: number | null | undefined): EvidenceState {
  if (score == null) return 'pending';
  if (score >= 3.6) return 'proven';
  if (score >= 3.1) return 'insufficient';
  return 'contradicted';
}

function verdictState(verdict?: string): EvidenceState {
  if (verdict === 'pass') return 'proven';
  if (verdict === 'partial') return 'insufficient';
  if (verdict === 'fail') return 'contradicted';
  return 'pending';
}

function VerificationBadge({ status }: { status: string }) {
  if (status === 'verified') return <Badge tone="ok" dot>已证明</Badge>;
  if (status === 'partial') return <Badge tone="warn" dot>部分证明</Badge>;
  if (status === 'disputed') return <Badge tone="err" dot>存在矛盾</Badge>;
  if (status === 'untested') return <Badge>未考察</Badge>;
  return <Badge>{status}</Badge>;
}

function SkillStatusBadge({ status }: { status: SkillVerificationItem['status'] }) {
  if (status === 'verified') return <Badge tone="ok" dot>已证明</Badge>;
  if (status === 'partial') return <Badge tone="warn" dot>证据不足</Badge>;
  if (status === 'disputed') return <Badge tone="err" dot>存在矛盾</Badge>;
  return <Badge>未考察</Badge>;
}

export function Report() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { data: report } = useReport(id);
  const { data: session } = useSession(id);

  if (session && session.status !== 'completed') return <Navigate to={`/session/${id}`} replace />;
  if (!report || !session) return <Loading />;

  const jobName = session.job?.name ?? '目标岗位';
  const date = formatDate(session.completedAt ?? session.createdAt);
  const rounds = (session.rounds ?? []).filter((r) => r.status === 'evaluated');

  return (
    <div>
      <PageHeader
        eyebrow="面试报告"
        title="能力差距报告"
        description={`${jobName} · ${date} · 完成 ${report.metrics.questionCount} 题`}
        action={
          <div className="flex items-center gap-2">
            <Button variant="ghost" to="/records">
              面试记录
            </Button>
            <Button variant="primary" to="/configure">
              <Rocket className="size-4" /> 再练一场
            </Button>
          </div>
        }
      />

      {/* 三个业务结论 */}
      <BusinessAnswers report={report} />

      {/* 能力评估 */}
      <section className="mb-6 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Panel>
          <PanelHeader eyebrow="ABILITY" title="能力雷达" />
          <PanelBody>
            <RadarChart scores={report.abilityScores} />
            <div className="mt-4">
              <AbilityBars scores={report.abilityScores} />
            </div>
          </PanelBody>
        </Panel>
        <Panel>
          <PanelHeader eyebrow="METRICS" title="本场表现统计" />
          <PanelBody className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Metric label="初答平均分" value={report.metrics.initialAnswerAverage} suffix="/5" />
              <Metric
                label="追问后平均分"
                value={report.metrics.postFollowupAverage}
                suffix="/5"
                highlight
              />
            </div>
            <div>
              <div className="micro-label mb-2">各题型得分</div>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(report.metrics.questionTypeScores).map(([type, value]) => (
                  <div key={type} className="rounded border border-line bg-surface px-2.5 py-2 text-center">
                    <div className="font-mono text-sm text-ink mono-num">{Number(value).toFixed(1)}</div>
                    <div className="mt-0.5 text-[11px] text-ink-tertiary">{typeLabel(type)}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="micro-label mb-2">难度分布</div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(report.metrics.difficultyScores).map(([level, value]) => (
                  <Tag key={level}>
                    {DIFFICULTY_LABEL[level] ?? level} {Number(value).toFixed(1)}
                  </Tag>
                ))}
              </div>
            </div>
            <div className="border-t border-line pt-3 text-xs leading-5 text-ink-tertiary">
              追问 {report.metrics.followupCount} 次 · 首答与追问平均差 {(
                report.metrics.postFollowupAverage - report.metrics.initialAnswerAverage
              ).toFixed(1)} 分，说明「追问后修正」对最终结论影响明显。
            </div>
          </PanelBody>
        </Panel>
      </section>

      {/* JD 验证矩阵 */}
      <section className="mb-6">
        <div className="mb-3 flex items-center gap-2">
          <Target className="size-4 text-accent" />
          <h2 className="text-sm font-semibold">JD 能力验证矩阵</h2>
        </div>
        <Panel>
          <div className="overflow-x-auto thin-scroll">
            <table className="w-full min-w-[820px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-line">
                  {['岗位要求', '权重', '简历声明', '实际考题', '评分', '验证状态', '改进建议'].map((head, index) => (
                    <th
                      key={head}
                      className={cn(
                        'px-4 py-2.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-tertiary',
                        index === 0 && 'w-[26%]',
                      )}
                    >
                      {head}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {report.jdVerificationMatrix.map((item) => (
                  <MatrixRow key={item.requirementId} item={item} />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </section>

      {/* 简历声明验证 */}
      <section className="mb-6">
        <div className="mb-3 flex items-center gap-2">
          <ShieldCheck className="size-4 text-accent" />
          <h2 className="text-sm font-semibold">简历声明验证结果</h2>
        </div>
        <Panel>
          <PanelBody className="space-y-2.5">
            {report.skillVerification && report.skillVerification.length > 0 ? (
              report.skillVerification.map((item) => (
                <div key={item.skill} className="flex flex-col gap-2 rounded border border-line bg-surface px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{item.skill}</span>
                    <span className="font-mono text-[10px] text-ink-tertiary">声称：{levelLabel(item.claimedLevel)}</span>
                    {item.topics?.slice(0, 3).map((topic) => (
                      <Tag key={topic}>{topic}</Tag>
                    ))}
                  </div>
                  <div className="flex items-center gap-3">
                    <SkillStatusBadge status={item.status} />
                    <span className="font-mono text-sm text-ink mono-num">
                      {item.avgScore?.toFixed(1) ?? '—'}
                      <span className="text-xs text-ink-tertiary">/5</span>
                    </span>
                  </div>
                  {item.recommendation && (
                    <p className="w-full text-xs leading-5 text-ink-tertiary sm:w-auto sm:max-w-[280px]">{item.recommendation}</p>
                  )}
                </div>
              ))
            ) : (
              <div className="rounded border border-dashed border-line p-3 text-xs text-ink-tertiary">暂无技能核验数据</div>
            )}
          </PanelBody>
        </Panel>
      </section>

      {/* 每道题评估 */}
      <section className="mb-6">
        <div className="mb-3 flex items-center gap-2">
          <ListOrdered className="size-4 text-accent" />
          <h2 className="text-sm font-semibold">逐题评估与证据</h2>
        </div>
        <div className="space-y-3">
          {rounds.map((round) => (
            <RoundCard key={round.id} round={round} onReplay={() => navigate('/configure')} />
          ))}
        </div>
      </section>

      {/* 优势 · 薄弱项 · 训练建议 */}
      <section className="mb-6 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Panel>
          <PanelHeader eyebrow="STRENGTHS" title="优势" />
          <PanelBody className="space-y-2.5">
            {report.strengths.map((item) => (
              <div key={item.topic} className="flex items-center justify-between">
                <span className="text-sm text-ink">{item.topic}</span>
                <span className="font-mono text-sm text-ok mono-num">{item.score.toFixed(1)}</span>
              </div>
            ))}
          </PanelBody>
        </Panel>
        <Panel>
          <PanelHeader eyebrow="WEAKNESSES" title="薄弱项" />
          <PanelBody className="space-y-2.5">
            {report.weaknesses.map((item) => (
              <div key={item.topic} className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-sm text-ink">
                  <span className="font-mono text-[10px] text-ink-tertiary">#{item.priority}</span>
                  {item.topic}
                </span>
                <span className="font-mono text-sm text-warn mono-num">{item.score.toFixed(1)}</span>
              </div>
            ))}
          </PanelBody>
        </Panel>
        <Panel>
          <PanelHeader eyebrow="TRAINING" title="训练建议" />
          <PanelBody className="space-y-2.5">
            {report.trainingPlan.map((plan) => (
              <div key={plan.order} className="rounded border border-line bg-surface px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-ink-tertiary">第 {plan.order} 周</span>
                  <span className="text-sm font-medium">{plan.topic}</span>
                </div>
                <p className="mt-1 text-xs leading-5 text-ink-secondary">{plan.action}</p>
                <p className="mt-1 font-mono text-[10px] text-ink-tertiary">达成：{plan.successCriteria}</p>
              </div>
            ))}
          </PanelBody>
        </Panel>
      </section>

      {/* 下一场建议 */}
      <section className="panel flex flex-col items-start justify-between gap-4 p-4 sm:flex-row sm:items-center">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-9 items-center justify-center rounded border border-accent/40 bg-accent-dim">
            <Sparkles className="size-4 text-accent" />
          </span>
          <div>
            <div className="text-sm font-semibold">下一场面试建议配置</div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-secondary">
              <Tag>{report.metrics.recommendedRole || '目标岗位'}</Tag>
              <Tag>{DIFFICULTY_LABEL[report.metrics.recommendedDifficulty] ?? '中级'}</Tag>
              <Tag>{report.metrics.questionCount} 题</Tag>
              {report.weaknesses.slice(0, 3).map((weakness) => (
                <Tag key={weakness.topic}>重点：{weakness.topic}</Tag>
              ))}
            </div>
            <div className="mt-2 text-xs text-ink-tertiary">
              依据本场弱项调整出题方向，并在题库中加入系统设计专项。
            </div>
          </div>
        </div>
        <Button variant="primary" to="/configure">
          按此配置再练一场 <ArrowRight className="size-4" />
        </Button>
      </section>
    </div>
  );
}

function typeLabel(type: string): string {
  return (
    { theory: '概念题', scenario: '场景题', coding: '算法题' }[type] ?? type
  );
}

function levelLabel(level: string): string {
  return (
    { fluent: '精通', experienced: '熟练', proficient: '扎实', familiar: '了解', beginner: '入门' }[level] ?? level
  );
}

function Metric({ label, value, suffix, highlight }: { label: string; value: number; suffix?: string; highlight?: boolean }) {
  return (
    <div className={cn('rounded border px-3 py-2.5', highlight ? 'border-accent/40 bg-accent-dim' : 'border-line bg-surface')}>
      <div className="micro-label">{label}</div>
      <div className="mt-1 flex items-baseline gap-1 font-mono mono-num">
        <span className={cn('text-2xl font-semibold', highlight ? 'text-accent' : 'text-ink')}>{value.toFixed(1)}</span>
        {suffix && <span className="text-xs text-ink-tertiary">{suffix}</span>}
      </div>
    </div>
  );
}

function BusinessAnswers({ report }: { report: InterviewReport }) {
  const verified = report.skillVerification?.filter((s) => s.status === 'verified').length ?? 0;
  const partial = report.skillVerification?.filter((s) => s.status === 'partial').length ?? 0;
  const disputed = report.skillVerification?.filter((s) => s.status === 'disputed').length ?? 0;
  const nextFocus = report.weaknesses[0];
  return (
    <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
      <Panel>
        <PanelBody>
          <div className="micro-label mb-2">目标岗位匹配程度</div>
          <div className="flex items-baseline gap-1.5 font-mono mono-num">
            <span className={cn('text-3xl font-semibold', report.overallScore >= 70 ? 'text-ok' : report.overallScore >= 50 ? 'text-accent' : 'text-warn')}>
              {report.overallScore}
            </span>
            <span className="text-sm text-ink-secondary">%</span>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${Math.max(2, Math.min(100, report.overallScore))}%` }}
            />
          </div>
          <p className="mt-2.5 text-xs leading-5 text-ink-tertiary">
            {report.overallScore >= 70 ? '匹配度良好，可冲刺目标岗位。' : report.overallScore >= 50 ? '部分匹配，存在明确补强空间。' : '差距较大，建议降低难度后针对性训练。'}
          </p>
        </PanelBody>
      </Panel>
      <Panel>
        <PanelBody>
          <div className="micro-label mb-2">简历声明验证</div>
          <div className="flex flex-wrap gap-1.5">
            <Badge tone="ok" dot>已证明 {verified}</Badge>
            <Badge tone="warn" dot>证据不足 {partial}</Badge>
            <Badge tone="err" dot>存在矛盾 {disputed}</Badge>
          </div>
          <p className="mt-2.5 text-xs leading-5 text-ink-tertiary">
            {disputed > 0
              ? `有 ${disputed} 项声明与实际表现不符，请在下次面试前优先修正简历表述或补足能力。`
              : verified > 0
                ? `有 ${verified} 项声明在面试中获得充分证据。`
                : '本场尚未验证到具体声明。'}
          </p>
        </PanelBody>
      </Panel>
      <Panel>
        <PanelBody>
          <div className="micro-label mb-2">下一次重点练习</div>
          {nextFocus ? (
            <>
              <div className="flex items-center gap-2">
                <TrendingUp className="size-4 text-warn" />
                <span className="text-lg font-semibold">{nextFocus.topic}</span>
                <span className="font-mono text-sm text-warn mono-num">{nextFocus.score.toFixed(1)}</span>
              </div>
              <p className="mt-2.5 text-xs leading-5 text-ink-tertiary">
                已列入训练计划第 {report.trainingPlan.find((p) => p.topic === nextFocus.topic)?.order ?? 1} 步。完成后用一场面试检验达标情况。
              </p>
            </>
          ) : (
            <p className="text-sm text-ink-tertiary">暂无数据</p>
          )}
        </PanelBody>
      </Panel>
    </section>
  );
}

function MatrixRow({ item }: { item: JDVerificationItem }) {
  const [open, setOpen] = useState(false);
  const resumeState: EvidenceState = item.resumeClaimStatus === 'matched' ? 'proven' : item.resumeClaimStatus === 'partial' ? 'insufficient' : 'pending';
  const links: TraceLink[] = [
    {
      label: '简历声明',
      state: resumeState,
      detail: item.resumeEvidence.length
        ? (item.resumeEvidence as Array<{ claim: string }>).map((e) => e.claim).join('；')
        : '简历未声明相关技能，作为出题盲区处理。',
    },
    {
      label: 'JD 要求',
      state: 'proven',
      detail: `${item.requirementText}（权重 ${Math.round(item.weight * 100)}%）`,
    },
    {
      label: '实际考题',
      state: item.actualQuestions.length ? 'proven' : 'pending',
      detail: item.actualQuestions.length
        ? item.actualQuestions.map((q) => `${CATEGORY_LABEL[q.topic] ?? q.topic} · ${q.questionText}`).join('\n')
        : '本轮未考察该要求。',
    },
    {
      label: '回答评分',
      state: scoreState(item.score),
      detail: item.score == null ? '无评分' : `综合 ${item.score.toFixed(1)} / 5${item.supportEvidence.length ? `，其中 ${item.supportEvidence.map((s) => `${s.score?.toFixed(1) ?? '—'} 分`).join('、')}` : ''}`,
    },
    {
      label: '能力结论',
      state: item.verificationStatus === 'verified' ? 'proven' : item.verificationStatus === 'partial' ? 'insufficient' : item.verificationStatus === 'disputed' ? 'contradicted' : 'pending',
      detail: item.improvementRecommendation,
    },
  ];
  return (
    <>
      <tr
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') setOpen((v) => !v);
        }}
        className="cursor-pointer align-top transition-colors hover:bg-content"
      >
        <td className="px-4 py-3">
          <div className="flex items-start gap-2">
            <ChevronRight className={cn('mt-0.5 size-3.5 shrink-0 text-ink-tertiary transition-transform', open && 'rotate-90')} />
            <span className="text-sm leading-6">{item.requirementText}</span>
          </div>
        </td>
        <td className="px-4 py-3 font-mono text-xs text-ink-secondary mono-num">{Math.round(item.weight * 100)}%</td>
        <td className="px-4 py-3">
          <Badge tone={item.resumeClaimStatus === 'matched' ? 'ok' : item.resumeClaimStatus === 'partial' ? 'warn' : 'neutral'}>
            {item.resumeClaimStatus === 'matched' ? '已匹配' : item.resumeClaimStatus === 'partial' ? '部分匹配' : item.resumeClaimStatus === 'missing' ? '未声明' : '未知'}
          </Badge>
        </td>
        <td className="px-4 py-3">
          {item.actualQuestions.length ? (
            <span className="font-mono text-xs text-ink-secondary">{item.actualQuestions.length} 题</span>
          ) : (
            <span className="font-mono text-xs text-ink-tertiary">—</span>
          )}
        </td>
        <td className="px-4 py-3 font-mono text-sm text-ink mono-num">{item.score?.toFixed(1) ?? '—'}</td>
        <td className="px-4 py-3"><VerificationBadge status={item.verificationStatus} /></td>
        <td className="max-w-[240px] px-4 py-3 text-xs leading-5 text-ink-tertiary">{item.improvementRecommendation}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="border-t border-line bg-content px-4 py-3">
            <TraceChain links={links} defaultOpen />
          </td>
        </tr>
      )}
    </>
  );
}

function RoundCard({ round, onReplay }: { round: InterviewRound; onReplay: () => void }) {
  const [open, setOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const initial = round.candidateAnswers[0];
  const followups = round.candidateAnswers.slice(1);
  const score = round.score ?? initial?.evaluation?.score ?? null;
  const links: TraceLink[] = [
    {
      label: '简历声明',
      state: round.resumeProbe ? verdictState(round.verdict) : 'pending',
      detail: round.resumeProbe
        ? `${round.resumeProbe.skills.join('、')}${round.resumeProbe.project ? `（项目：${round.resumeProbe.project.name}）` : ''}`
        : '本题不针对具体简历声明。',
    },
    {
      label: 'JD 要求',
      state: round.targetRequirementId ? 'proven' : 'pending',
      detail: round.targetRequirementId ? `关联岗位要求 ${round.targetRequirementId}` : '未关联。',
    },
    {
      label: '实际考题',
      state: 'proven',
      detail: round.questionText,
    },
    {
      label: '回答证据',
      state: 'proven',
      detail: (
        <div className="space-y-2">
          {initial && (
            <div>
              <div className="micro-label mb-1">首答 · {initial.evaluation?.score?.toFixed(1) ?? '—'}/5</div>
              <p className="whitespace-pre-wrap text-xs leading-5">{initial.answer}</p>
            </div>
          )}
          {followups.map((followup, index) => (
            <div key={index}>
              <div className="micro-label mb-1">追问修正 · {followup.evaluation?.score?.toFixed(1) ?? '—'}/5</div>
              <p className="whitespace-pre-wrap text-xs leading-5">{followup.answer}</p>
            </div>
          ))}
        </div>
      ),
    },
    {
      label: '评分与结论',
      state: scoreState(score),
      detail: (
        <div>
          <div className="mb-1 font-mono text-sm text-ink mono-num">
            {score?.toFixed(1) ?? '—'} <span className="text-xs text-ink-tertiary">/ 5</span>
          </div>
          {round.feedback && <p className="text-xs leading-5">{round.feedback}</p>}
          {round.weakPoint && <p className="mt-1 text-xs text-warn">薄弱：{round.weakPoint}</p>}
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Button size="sm" variant="ghost" onClick={onReplay}>
              针对该题再练 <ArrowRight className="size-3" />
            </Button>
          </div>
        </div>
      ),
    },
  ];
  return (
    <Panel>
      <PanelHeader
        eyebrow={`ROUND ${String(round.sequence).padStart(2, '0')}`}
        title={
          <span className="flex flex-wrap items-center gap-2">
            {CATEGORY_LABEL[round.category] ?? round.category}
            <Tag>{DIFFICULTY_LABEL[round.difficulty] ?? round.difficulty}</Tag>
            <Tag>{round.topic}</Tag>
          </span>
        }
        action={
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-ink mono-num">
              {score?.toFixed(1) ?? '—'}<span className="text-xs text-ink-tertiary">/5</span>
            </span>
            <Badge tone={scoreState(score) === 'proven' ? 'ok' : scoreState(score) === 'insufficient' ? 'warn' : 'neutral'}>
              {round.verdict === 'pass' ? '通过' : round.verdict === 'partial' ? '部分' : round.verdict === 'fail' ? '未过' : '—'}
            </Badge>
          </div>
        }
      />
      <PanelBody>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="w-full text-left text-sm leading-6 text-ink-secondary hover:text-ink"
        >
          <span className="flex items-start gap-2">
            <ChevronRight className={cn('mt-1 size-3.5 shrink-0 text-ink-tertiary transition-transform', open && 'rotate-90')} />
            {round.questionText}
          </span>
        </button>
        {open && (
          <div className="mt-3 space-y-2">
            {initial && (
              <div className="rounded border border-line bg-surface p-3">
                <div className="micro-label mb-1.5">首答 · {initial.evaluation?.score?.toFixed(1) ?? '—'}/5 · {initial.evaluation?.verdict ?? ''}</div>
                <p className="whitespace-pre-wrap text-sm leading-6 text-ink-secondary">{initial.answer}</p>
              </div>
            )}
            {followups.map((followup, index) => (
              <div key={index} className="rounded border border-warn/30 bg-warn-dim/40 p-3">
                <div className="micro-label mb-1.5 text-warn">追问修正 · {followup.evaluation?.score?.toFixed(1) ?? '—'}/5</div>
                <p className="whitespace-pre-wrap text-sm leading-6 text-ink-secondary">{followup.answer}</p>
              </div>
            ))}
            {round.followupQuestions.map((fq, index) => (
              <div key={index} className="rounded border border-line bg-surface p-3">
                <div className="micro-label mb-1.5">面试官追问</div>
                <p className="text-sm leading-6 text-ink-secondary">{fq.question}</p>
              </div>
            ))}
            <div className="flex items-center justify-between border-t border-line pt-3">
              <span className="text-xs text-ink-tertiary">
                {round.weakPoint ? `薄弱点：${round.weakPoint}` : '无显著薄弱点'}
              </span>
              <Button size="sm" variant="ghost" onClick={() => setTraceOpen((v) => !v)}>
                证据溯源 <ChevronRight className={cn('size-3.5 transition-transform', traceOpen && 'rotate-90')} />
              </Button>
            </div>
            {traceOpen && (
              <div className="rounded border border-line p-3">
                <TraceChain links={links} defaultOpen />
              </div>
            )}
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}
