import {
  ArrowRight,
  BarChart3,
  CirclePlay,
  History,
  Target,
} from 'lucide-react';
import { Link, Navigate, useNavigate } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState, Loading } from '@/components/ui/feedback';
import { useJobs, useOnboarded, useResumes, useSessions } from '@/hooks/use-cs-query';
import { abilityPercent, formatRelative } from '@/lib/format';
import type { InterviewSession } from '@/lib/types';

function StatCard({
  label,
  value,
  suffix,
  icon: Icon,
  hint,
}: {
  label: string;
  value: string | number;
  suffix?: string;
  icon: React.ComponentType<{ className?: string }>;
  hint?: string;
}) {
  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="micro-label">{label}</span>
        <Icon className="size-4 text-ink-tertiary" />
      </div>
      <div className="flex items-baseline gap-1 font-mono mono-num">
        <span className="text-3xl font-semibold tracking-tight">{value}</span>
        {suffix && <span className="text-sm text-ink-secondary">{suffix}</span>}
      </div>
      {hint && <div className="mt-2 text-xs text-ink-tertiary">{hint}</div>}
    </div>
  );
}

function AbilityBars({ scores }: { scores: Record<string, number> }) {
  const sorted = Object.entries(scores)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  return (
    <div className="space-y-3.5">
      {sorted.map(([label, score]) => (
        <div key={label} className="flex items-center gap-3">
          <span className="w-16 shrink-0 font-mono text-[11px] text-ink-secondary">{label}</span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
            <div
              className="h-full rounded-full bg-accent/80"
              style={{ width: `${abilityPercent(score)}%` }}
            />
          </div>
          <span className="w-8 shrink-0 text-right font-mono text-xs text-ink mono-num">
            {score.toFixed(1)}
          </span>
        </div>
      ))}
    </div>
  );
}

function sessionRow(session: InterviewSession) {
  const completed = session.status === 'completed';
  return {
    id: session.id,
    label: session.job?.name ?? 'Go 后端开发',
    time: formatRelative(session.updatedAt ?? session.createdAt),
    score: completed ? session.report?.overallScore : null,
    progress: `${session.completedQuestionCount}/${session.maxQuestions}`,
    status: session.status,
  };
}

export function Overview() {
  const navigate = useNavigate();
  const { data: onboarded } = useOnboarded();
  const { data: sessions = [] } = useSessions();
  const { data: resumes = [] } = useResumes();
  const { data: jobs = [] } = useJobs();

  if (onboarded === false) return <Navigate to="/onboarding" replace />;
  if (onboarded == null) return <Loading />;

  const completed = sessions
    .filter((s) => s.status === 'completed' && s.report)
    .sort((a, b) => (b.completedAt ?? '').localeCompare(a.completedAt ?? ''));
  const active = sessions.filter((s) => !['completed', 'aborted'].includes(s.status));
  const latestReport = completed[0]?.report;

  const matchPercent = latestReport?.overallScore ?? null;
  const verifiedCount = latestReport
    ? latestReport.jdVerificationMatrix.filter((item) => item.verificationStatus === 'verified').length
    : null;
  const jdTotal = latestReport?.jdVerificationMatrix.length ?? 0;
  const nextFocus = latestReport?.weaknesses[0]?.topic ?? null;
  const abilityScores = latestReport?.abilityScores ?? null;

  const hasResume = resumes.length > 0;
  const hasJob = jobs.length > 0;

  return (
    <div>
      <PageHeader
        eyebrow="面试概览"
        title="下一场面试，从这里开始"
        description="追踪目标岗位匹配度、简历声明验证进度与能力差距，针对性准备每一场面试。"
        action={
          <Button variant="primary" to="/configure">
            <CirclePlay className="size-4" /> 新建面试
          </Button>
        }
      />

      {active.length > 0 && (
        <div className="panel mb-6 flex flex-col items-start justify-between gap-4 p-4 sm:flex-row sm:items-center">
          <div className="flex items-center gap-3">
            <span className="relative flex size-9 items-center justify-center rounded border border-accent/40 bg-accent-dim">
              <History className="size-4 text-accent" />
            </span>
            <div>
              <div className="text-sm font-medium">有一场进行中的面试</div>
              <div className="mt-0.5 font-mono text-xs text-ink-secondary">
                {active[0]?.job?.name ?? '目标岗位'} · 已完成 {active[0]?.completedQuestionCount}/{active[0]?.maxQuestions} 题
              </div>
            </div>
          </div>
          <Button variant="primary" to={`/session/${active[0]?.id}`}>
            继续面试 <ArrowRight className="size-4" />
          </Button>
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard
          label="目标岗位匹配度"
          value={matchPercent ?? '—'}
          suffix="%"
          icon={Target}
          hint={latestReport ? '来自最近一场面试报告' : '完成第一场面试后生成'}
        />
        <StatCard
          label="已完成面试"
          value={completed.length}
          icon={BarChart3}
          hint={completed.length ? `最近一场 ${formatRelative(completed[0]?.completedAt)}` : '从新建面试开始'}
        />
        <StatCard
          label="已验证 JD 要求"
          value={verifiedCount ?? '—'}
          suffix={jdTotal ? `/ ${jdTotal}` : undefined}
          icon={Target}
          hint={jdTotal ? '已获得充分证据的必备/加分项' : '在 JD 中心查看覆盖情况'}
        />
        <StatCard
          label="下个练习重点"
          value={nextFocus ?? '—'}
          icon={Target}
          hint={latestReport ? '来自薄弱项分析，见训练建议' : '完成面试后生成训练计划'}
        />
      </div>

      {abilityScores && (
        <div className="panel mb-6 p-4">
          <div className="micro-label mb-4">能力差距概览</div>
          <AbilityBars scores={abilityScores} />
        </div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold">最近面试</h2>
        <Button size="sm" variant="ghost" to="/records">
          全部记录 <ArrowRight className="size-3.5" />
        </Button>
      </div>

      {sessions.length === 0 ? (
        <EmptyState
          icon={History}
          title="还没有面试记录"
          description={hasResume && hasJob ? '配置一场模拟面试，立即开始第一次训练。' : '先上传简历并添加目标 JD，即可开始模拟面试。'}
          action={
            <Button variant="primary" to={hasResume && hasJob ? '/configure' : '/onboarding'}>
              开始第一次面试
            </Button>
          }
        />
      ) : (
        <div className="divide-y divide-line border-y border-line">
          {sessions.slice(0, 5).map((session) => {
            const row = sessionRow(session);
            const isActive = !['completed', 'aborted'].includes(row.status);
            return (
              <div
                key={session.id}
                className="grid grid-cols-1 gap-2 py-3.5 transition-colors hover:bg-content sm:grid-cols-[1fr_auto_auto] sm:items-center sm:gap-4 sm:px-2"
              >
                <Link to={isActive ? `/session/${session.id}` : `/report/${session.id}`} className="min-w-0">
                  <div className="truncate text-sm font-medium hover:text-accent">{row.label}</div>
                  <div className="mt-0.5 font-mono text-xs text-ink-tertiary">
                    {row.time} · {row.progress} 题
                  </div>
                </Link>
                <div className="flex items-center gap-3">
                  {row.score != null && (
                    <span className="font-mono text-sm text-ink mono-num">{row.score}<span className="text-xs text-ink-tertiary">%</span></span>
                  )}
                  {isActive ? (
                    <Badge tone="accent" dot>进行中</Badge>
                  ) : row.status === 'aborted' ? (
                    <Badge>已中止</Badge>
                  ) : (
                    <Badge tone="ok" dot>已完成</Badge>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => navigate(isActive ? `/session/${session.id}` : `/report/${session.id}`)}
                >
                  {isActive ? '继续' : '查看报告'}
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
