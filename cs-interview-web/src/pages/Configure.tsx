import {
  BriefcaseBusiness,
  CirclePlay,
  FileText,
  ListChecks,
  ShieldCheck,
  Timer,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge, Tag } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Spinner, useToast } from '@/components/ui/feedback';
import { Field, Input, Select } from '@/components/ui/inputs';
import { Segmented } from '@/components/ui/Segmented';
import { Toggle } from '@/components/ui/Toggle';
import { useCsMutations, useDatasets, useJobs, useKnowledgeConfig, useResumes } from '@/hooks/use-cs-query';
import { readHighRiskClaims } from '@/lib/claims';
import { makeDraftSaver, readStorage, clearStorage } from '@/lib/storage';
import { cn } from '@/lib/cn';
import type { InterviewDifficulty } from '@/lib/types';

const DRAFT_KEY = 'cs_configure_draft';

const TOPICS: Array<{ id: string; label: string }> = [
  { id: 'go-concurrency', label: 'Go 并发' },
  { id: 'mysql', label: '数据库' },
  { id: 'redis', label: '缓存' },
  { id: 'kafka', label: '消息队列' },
  { id: 'system-design', label: '系统设计' },
  { id: 'algorithms', label: '算法' },
  { id: 'network', label: '网络' },
  { id: 'container', label: '容器/K8s' },
  { id: 'frontend', label: '前端' },
];

const STACK_TO_TOPIC: Record<string, string> = {
  Go: 'go-concurrency',
  MySQL: 'mysql',
  Redis: 'redis',
  Kafka: 'kafka',
  Docker: 'container',
  K8s: 'container',
};

const DIFFICULTY_LEVEL: Record<InterviewDifficulty, string> = {
  beginner: '初级',
  medium: '中级',
  advanced: '高级',
};

interface ConfigureDraft {
  resumeId: string;
  jobId: string;
  targetRole: string;
  difficulty: InterviewDifficulty;
  technologyStack: string[];
  focusTopics: string[];
  excludedTopics: string[];
  questionCount: number;
  maxFollowups: number;
  includeCoding: boolean;
  enableCodeExecution: boolean;
}

const defaultDraft = (resumeId = '', jobId = ''): ConfigureDraft => ({
  resumeId,
  jobId,
  targetRole: '',
  difficulty: 'medium',
  technologyStack: [],
  focusTopics: ['go-concurrency', 'mysql', 'redis', 'kafka', 'system-design', 'algorithms'],
  excludedTopics: [],
  questionCount: 6,
  maxFollowups: 2,
  includeCoding: true,
  enableCodeExecution: true,
});

function skillOverlap(a: string[], b: string[]): boolean {
  return a.some((skillA) => b.some((skillB) => skillA === skillB || skillA.includes(skillB) || skillB.includes(skillA)));
}

export function Configure() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [searchParams] = useSearchParams();
  const { data: resumes = [] } = useResumes();
  const { data: jobs = [] } = useJobs();
  const { data: knowledge } = useKnowledgeConfig();
  const { data: datasets = [] } = useDatasets();
  const { launch } = useCsMutations();

  const parsedResumes = resumes.filter((r) => r.parseStatus === 'parsed');
  const parsedJobs = jobs.filter((j) => j.extraction);

  const [draft, setDraft] = useState<ConfigureDraft>(() => {
    const stored = readStorage<ConfigureDraft | null>(DRAFT_KEY, null);
    const urlResume = searchParams.get('resume');
    const merged: ConfigureDraft = stored
      ? stored
      : defaultDraft(urlResume ?? '', '');
    if (urlResume && stored) {
      merged.resumeId = urlResume;
    }
    return merged;
  });

  const saver = useMemo(() => makeDraftSaver<ConfigureDraft>(DRAFT_KEY, 600), []);
  useEffect(() => {
    saver.save(draft);
  }, [draft, saver]);

  const selectedResume = parsedResumes.find((r) => r.id === draft.resumeId);
  const selectedJob = parsedJobs.find((j) => j.id === draft.jobId);

  // URL 预选简历或草稿仅有 id 时，补派生技术栈与考察主题
  useEffect(() => {
    if (!draft.resumeId || draft.technologyStack.length > 0) return;
    const resume = parsedResumes.find((r) => r.id === draft.resumeId);
    const stack = resume?.extraction?.technologyStack ?? [];
    if (stack.length === 0) return;
    const focus = Array.from(
      new Set(stack.map((s) => STACK_TO_TOPIC[s]).filter((v): v is string => Boolean(v))),
    );
    setDraft((prev) => ({
      ...prev,
      technologyStack: stack,
      targetRole: resume?.extraction?.targetRole ?? prev.targetRole,
      focusTopics: focus.length ? focus : prev.focusTopics,
    }));
  }, [draft.resumeId, draft.technologyStack.length, parsedResumes]);

  const set = <K extends keyof ConfigureDraft>(key: K, value: ConfigureDraft[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const handleResumeChange = (resumeId: string) => {
    const resume = parsedResumes.find((r) => r.id === resumeId);
    const stack = resume?.extraction?.technologyStack ?? [];
    const focus = Array.from(
      new Set(stack.map((s) => STACK_TO_TOPIC[s]).filter((v): v is string => Boolean(v))),
    );
    setDraft((prev) => ({
      ...prev,
      resumeId,
      technologyStack: stack,
      targetRole: resume?.extraction?.targetRole ?? prev.targetRole,
      focusTopics: focus.length ? focus : prev.focusTopics,
    }));
  };

  const coverage = useMemo(() => {
    const reqs = selectedJob?.extraction?.requirements ?? [];
    const must = reqs.filter((r) => r.category === 'must_have');
    const covered = must.filter((r) => skillOverlap(draft.technologyStack, r.skills)).length;
    return { must, covered, total: must.length };
  }, [selectedJob, draft.technologyStack]);

  const highRiskClaims = selectedResume
    ? readHighRiskClaims(selectedResume.id, selectedResume.extraction)
    : [];

  const estimatedMinutes = draft.questionCount * 6 + (draft.includeCoding ? 8 : 0);

  const canStart = Boolean(draft.resumeId && draft.jobId);

  const handleStart = () => {
    if (!canStart) return;
    launch.mutate(
      {
        resumeId: draft.resumeId,
        jobId: draft.jobId,
        name: selectedResume?.preview?.name ?? '候选人',
        targetRole: draft.targetRole || selectedResume?.extraction?.targetRole || selectedJob?.name || '后端开发',
        targetLevel: DIFFICULTY_LEVEL[draft.difficulty],
        technologyStack: draft.technologyStack,
        focusTopics: draft.focusTopics,
        excludedTopics: draft.excludedTopics,
        initialDifficulty: draft.difficulty,
        preferredCategories: draft.includeCoding
          ? ['baguwen', 'interview_experience', 'leetcode']
          : ['baguwen', 'interview_experience'],
        questionCount: draft.questionCount,
        maxFollowups: draft.maxFollowups,
        enableCodeExecution: draft.enableCodeExecution,
      },
      {
        onSuccess: (session) => {
          clearStorage(DRAFT_KEY);
          toast('success', '面试已创建', '第一题已准备好，开始回答吧。');
          navigate(`/session/${session.id}`);
        },
        onError: (err) => toast('error', '创建面试失败', err.message),
      },
    );
  };

  return (
    <div>
      <PageHeader
        eyebrow="新建面试"
        title="配置本场模拟面试"
        description="选择简历与 JD 作为证据来源，设定面试目标与规则。表单会自动保存草稿。"
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
        {/* 表单 */}
        <div className="space-y-5">
          {/* 候选人与岗位证据 */}
          <section className="panel p-4">
            <div className="micro-label mb-4">01 · 候选人与岗位证据</div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="候选人简历" htmlFor="configure-resume" hint="选择已解析简历作为声明来源">
                <Select id="configure-resume" value={draft.resumeId} onChange={(event) => handleResumeChange(event.target.value)}>
                  <option value="">请选择简历…</option>
                  {parsedResumes.map((resume) => (
                    <option key={resume.id} value={resume.id}>
                      {resume.preview?.name ?? resume.fileName}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="目标 JD" htmlFor="configure-job" hint="选择已解析 JD 作为岗位要求来源">
                <Select id="configure-job" value={draft.jobId} onChange={(event) => set('jobId', event.target.value)}>
                  <option value="">请选择 JD…</option>
                  {parsedJobs.map((job) => (
                    <option key={job.id} value={job.id}>
                      {job.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            {parsedResumes.length === 0 && (
              <div className="mt-3 flex items-center justify-between rounded border border-warn/30 bg-warn-dim/40 px-3 py-2.5 text-xs text-ink-secondary">
                还没有已解析的简历，面试将无法开始。
                <Link to="/resumes" className="text-accent underline-offset-4 hover:underline">去上传</Link>
              </div>
            )}
            {parsedJobs.length === 0 && (
              <div className="mt-3 flex items-center justify-between rounded border border-warn/30 bg-warn-dim/40 px-3 py-2.5 text-xs text-ink-secondary">
                还没有已解析的 JD，面试将无法开始。
                <Link to="/jobs" className="text-accent underline-offset-4 hover:underline">去添加</Link>
              </div>
            )}
          </section>

          {/* 面试目标 */}
          <section className="panel p-4">
            <div className="micro-label mb-4">02 · 面试目标</div>
            <div className="space-y-4">
              <Field label="岗位方向" htmlFor="configure-role">
                <Input
                  id="configure-role"
                  value={draft.targetRole}
                  onChange={(event) => set('targetRole', event.target.value)}
                  placeholder="如：Go 后端开发工程师"
                />
              </Field>
              <Field label="难度">
                <Segmented<InterviewDifficulty>
                  value={draft.difficulty}
                  onChange={(value) => set('difficulty', value)}
                  options={[
                    { value: 'beginner', label: '初级' },
                    { value: 'medium', label: '中级' },
                    { value: 'advanced', label: '高级' },
                  ]}
                />
              </Field>
              <Field label="技术栈（逗号分隔）" htmlFor="configure-stack">
                <Input
                  id="configure-stack"
                  value={draft.technologyStack.join(', ')}
                  onChange={(event) =>
                    set(
                      'technologyStack',
                      event.target.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
                    )
                  }
                />
              </Field>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <div className="mb-1.5 text-xs font-medium text-ink-secondary">重点考察主题</div>
                  <div className="flex flex-wrap gap-1.5">
                    {TOPICS.map((topic) => {
                      const active = draft.focusTopics.includes(topic.id);
                      return (
                        <button
                          key={topic.id}
                          type="button"
                          aria-pressed={active}
                          onClick={() =>
                            set(
                              'focusTopics',
                              active
                                ? draft.focusTopics.filter((t) => t !== topic.id)
                                : [...draft.focusTopics, topic.id],
                            )
                          }
                          className={cn(
                            'rounded border px-2 py-1 font-mono text-[11px] transition-colors',
                            active
                              ? 'border-accent/50 bg-accent-dim text-accent'
                              : 'border-line bg-surface text-ink-tertiary hover:text-ink-secondary',
                          )}
                        >
                          {topic.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <div className="mb-1.5 text-xs font-medium text-ink-secondary">排除主题</div>
                  <div className="flex flex-wrap gap-1.5">
                    {TOPICS.map((topic) => {
                      const active = draft.excludedTopics.includes(topic.id);
                      return (
                        <button
                          key={topic.id}
                          type="button"
                          aria-pressed={active}
                          onClick={() =>
                            set(
                              'excludedTopics',
                              active
                                ? draft.excludedTopics.filter((t) => t !== topic.id)
                                : [...draft.excludedTopics, topic.id],
                            )
                          }
                          className={cn(
                            'rounded border px-2 py-1 font-mono text-[11px] transition-colors',
                            active
                              ? 'border-err/50 bg-err-dim text-err line-through'
                              : 'border-line bg-surface text-ink-tertiary hover:text-ink-secondary',
                          )}
                        >
                          {topic.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* 面试规则 */}
          <section className="panel p-4">
            <div className="micro-label mb-4">03 · 面试规则</div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="题目数量" hint="3 ~ 10 题">
                <Input
                  type="number"
                  min={3}
                  max={10}
                  value={draft.questionCount}
                  onChange={(event) =>
                    set('questionCount', Math.max(3, Math.min(10, Number(event.target.value) || 3)))
                  }
                />
              </Field>
              <Field label="最大追问次数" hint="0 ~ 3 次">
                <Input
                  type="number"
                  min={0}
                  max={3}
                  value={draft.maxFollowups}
                  onChange={(event) =>
                    set('maxFollowups', Math.max(0, Math.min(3, Number(event.target.value) || 0)))
                  }
                />
              </Field>
              <div className="flex items-center justify-between rounded border border-line bg-surface px-3 py-3 sm:col-span-2">
                <div>
                  <div className="text-sm font-medium">包含算法题</div>
                  <div className="mt-0.5 text-xs text-ink-tertiary">在题库中加入一道可运行的算法题（Monaco 编辑器）</div>
                </div>
                <Toggle
                  checked={draft.includeCoding}
                  onChange={(next) => set('includeCoding', next)}
                  label="包含算法题"
                />
              </div>
              <div className="flex items-center justify-between rounded border border-line bg-surface px-3 py-3 sm:col-span-2">
                <div>
                  <div className="text-sm font-medium">启用代码执行</div>
                  <div className="mt-0.5 text-xs text-ink-tertiary">算法题支持运行样例与提交隐藏用例</div>
                </div>
                <Toggle
                  checked={draft.enableCodeExecution}
                  onChange={(next) => set('enableCodeExecution', next)}
                  label="启用代码执行"
                />
              </div>
              <div className="sm:col-span-2">
                <div className="flex items-center justify-between rounded border border-line bg-surface px-3 py-3">
                  <span className="text-sm text-ink-secondary">预计时长</span>
                  <span className="font-mono text-sm text-ink mono-num">约 {estimatedMinutes} 分钟</span>
                </div>
              </div>
            </div>
            <Button
              variant="primary"
              size="lg"
              fullWidth
              className="mt-5"
              disabled={!canStart || launch.isPending}
              onClick={handleStart}
            >
              {launch.isPending ? <Spinner className="size-4" /> : <CirclePlay className="size-4" />}
              开始模拟面试
            </Button>
          </section>
        </div>

        {/* 计划摘要 */}
        <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <section className="panel p-4">
            <div className="micro-label mb-3">本场面试计划摘要</div>

            <div className="mb-4 flex items-center gap-2.5">
              <ListChecks className="size-4 text-accent" />
              <h3 className="text-sm font-semibold">将验证的 JD 要求</h3>
            </div>
            {coverage.must.length === 0 ? (
              <div className="rounded border border-dashed border-line p-3 text-xs text-ink-tertiary">选择 JD 后显示</div>
            ) : (
              <ul className="space-y-2">
                {coverage.must.map((req) => {
                  const covered = skillOverlap(draft.technologyStack, req.skills);
                  return (
                    <li key={req.requirementId} className="flex items-start gap-2 text-xs leading-5 text-ink-secondary">
                      <span className={cn('mt-1.5 size-1.5 shrink-0 rounded-full', covered ? 'bg-ok' : 'bg-warn')} />
                      <span className="min-w-0 flex-1">{req.text}</span>
                      <span className="shrink-0 font-mono text-[10px] text-ink-tertiary">
                        {Math.round(req.weight * 100)}%
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}

            <div className="mb-2 mt-5 flex items-center gap-2.5">
              <ShieldCheck className="size-4 text-warn" />
              <h3 className="text-sm font-semibold">简历高风险声明</h3>
            </div>
            {highRiskClaims.length === 0 ? (
              <div className="rounded border border-dashed border-line p-3 text-xs text-ink-tertiary">
                未识别到高风险声明
              </div>
            ) : (
              <ul className="space-y-2">
                {highRiskClaims.slice(0, 3).map((claim) => (
                  <li key={claim.id} className="flex items-start gap-2 text-xs leading-5 text-ink-secondary">
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warn" />
                    {claim.claim}
                  </li>
                ))}
              </ul>
            )}

            <div className="mb-2 mt-5 flex items-center gap-2.5">
              <BriefcaseBusiness className="size-4 text-ink-secondary" />
              <h3 className="text-sm font-semibold">预计能力覆盖率</h3>
            </div>
            <div className="flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
                <div
                  className="h-full rounded-full bg-accent/80"
                  style={{ width: `${coverage.total ? (coverage.covered / coverage.total) * 100 : 0}%` }}
                />
              </div>
              <span className="font-mono text-sm text-ink mono-num">
                {coverage.total ? Math.round((coverage.covered / coverage.total) * 100) : 0}%
              </span>
            </div>
            <div className="mt-1 text-xs text-ink-tertiary">
              基于简历技术栈与必备技能的重合度
            </div>

            <div className="mb-2 mt-5 flex items-center gap-2.5">
              <FileText className="size-4 text-ink-secondary" />
              <h3 className="text-sm font-semibold">知识源状态</h3>
            </div>
            <div className="space-y-1.5">
              {datasets.slice(0, 3).map((dataset) => {
                const enabled = knowledge?.enabled !== false;
                return (
                  <div key={dataset.id} className="flex items-center justify-between text-xs">
                    <span className="text-ink-secondary">{dataset.name}</span>
                    <span className={cn('font-mono', enabled ? 'text-ok' : 'text-ink-tertiary')}>
                      {dataset.documentCount} 篇 · {enabled ? '可用' : '已停用'}
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="mb-2 mt-5 flex items-center gap-2.5">
              <Timer className="size-4 text-ink-secondary" />
              <h3 className="text-sm font-semibold">预计用时</h3>
            </div>
            <div className="font-mono text-sm text-ink mono-num">约 {estimatedMinutes} 分钟</div>

            <div className="mt-4 border-t border-line pt-3">
              <div className="flex flex-wrap gap-1">
                {draft.focusTopics.slice(0, 5).map((topic) => {
                  const label = TOPICS.find((t) => t.id === topic)?.label ?? topic;
                  return <Tag key={topic}>{label}</Tag>;
                })}
                {draft.focusTopics.length > 5 && <Tag>+{draft.focusTopics.length - 5}</Tag>}
              </div>
            </div>
          </section>
        </aside>
      </div>

      <div className="mt-4 flex items-center gap-2 text-xs text-ink-tertiary">
        {selectedResume && <Badge>{selectedResume.fileName}</Badge>}
        {selectedJob && <Badge>{selectedJob.name}</Badge>}
        {!canStart && <span>完成“简历 + JD”选择后可开始。</span>}
      </div>
    </div>
  );
}
