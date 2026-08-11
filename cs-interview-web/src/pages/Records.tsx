import { History, Plus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/feedback';
import { Segmented } from '@/components/ui/Segmented';
import { useSessions } from '@/hooks/use-cs-query';
import { formatDate } from '@/lib/format';
import type { InterviewSession } from '@/lib/types';

type Filter = 'all' | 'active' | 'completed';

const STATUS_LABEL: Record<string, string> = {
  created: '已创建',
  preparing_question: '准备题目',
  awaiting_answer: '等待作答',
  evaluating: '评估中',
  completed: '已完成',
  aborted: '已中止',
};

export function Records() {
  const navigate = useNavigate();
  const { data: sessions = [] } = useSessions();
  const [filter, setFilter] = useState<Filter>('all');

  const sorted = useMemo(
    () =>
      [...sessions].sort((a, b) => (b.createdAt ?? '').localeCompare(a.createdAt ?? '')),
    [sessions],
  );

  const filtered = sorted.filter((session) => {
    if (filter === 'active') return !['completed', 'aborted'].includes(session.status);
    if (filter === 'completed') return session.status === 'completed';
    return true;
  });

  const openSession = (session: InterviewSession) => {
    if (session.status === 'completed') navigate(`/report/${session.id}`);
    else if (session.status !== 'aborted') navigate(`/session/${session.id}`);
  };

  return (
    <div>
      <PageHeader
        eyebrow="面试记录"
        title="历次模拟面试"
        description="回看每一场面试的进展与结果，从报告中的证据链定位能力缺口。"
        action={
          <Button variant="primary" to="/configure">
            <Plus className="size-4" /> 新建面试
          </Button>
        }
      />

      <div className="mb-4">
        <Segmented<Filter>
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: '全部' },
            { value: 'active', label: '进行中' },
            { value: 'completed', label: '已完成' },
          ]}
          className="max-w-xs"
        />
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={History}
          title={filter === 'completed' ? '还没有已完成的面试' : '这里暂时是空的'}
          description="配置一场模拟面试，完成后即可在这里查看能力差距报告。"
          action={
            <Button variant="primary" to="/configure">
              新建面试
            </Button>
          }
        />
      ) : (
        <div className="divide-y divide-line border-y border-line">
          {filtered.map((session) => {
            const isCompleted = session.status === 'completed';
            const isActive = !isCompleted && session.status !== 'aborted';
            return (
              <div
                key={session.id}
                className="grid grid-cols-1 gap-3 py-4 sm:grid-cols-[1fr_auto_auto] sm:items-center sm:gap-4"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">
                    {session.job?.name ?? 'Go 后端开发'}
                  </div>
                  <div className="mt-1 font-mono text-xs text-ink-tertiary">
                    开始于 {formatDate(session.startedAt ?? session.createdAt)} · 进度 {session.completedQuestionCount}/{session.maxQuestions}
                    {session.currentDifficulty && ` · 难度 ${session.currentDifficulty === 'beginner' ? '初级' : session.currentDifficulty === 'advanced' ? '高级' : '中级'}`}
                  </div>
                  {(isCompleted || isActive) && (
                    <div className="mt-1.5 font-mono text-[11px] text-ink-tertiary">
                      {session.report
                        ? `匹配度 ${session.report.overallScore}% · 弱项：${session.report.weaknesses[0]?.topic ?? '—'}`
                        : session.currentRoundSequence > 0
                          ? `当前第 ${session.currentRoundSequence} 题`
                          : '等待开始'}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  {isCompleted && session.report && (
                    <span className="font-mono text-sm text-ink mono-num">
                      {session.report.overallScore}
                      <span className="text-xs text-ink-tertiary">%</span>
                    </span>
                  )}
                  {isActive ? (
                    <Badge tone="accent" dot>进行中</Badge>
                  ) : isCompleted ? (
                    <Badge tone="ok" dot>{STATUS_LABEL[session.status]}</Badge>
                  ) : (
                    <Badge>{STATUS_LABEL[session.status] ?? session.status}</Badge>
                  )}
                </div>
                <div>
                  {(isCompleted || isActive) && (
                    <Button size="sm" variant="ghost" onClick={() => openSession(session)}>
                      {isCompleted ? '查看报告' : '继续面试'}
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
