import Editor from '@monaco-editor/react';
import {
  AlarmClock,
  CircleStop,
  Clock3,
  FileCode2,
  MessageSquareText,
  Play,
  Send,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, useBlocker, useNavigate, useParams } from 'react-router';
import { EvidenceTrack } from '@/components/evidence/EvidenceTrack';
import { Badge, Tag } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog, Loading, Spinner, useToast } from '@/components/ui/feedback';
import { Panel, PanelBody, PanelHeader } from '@/components/ui/Panel';
import { useInterviewFlow } from '@/hooks/use-interview-flow';
import { useJobs, useSession } from '@/hooks/use-cs-query';
import { useTheme } from '@/hooks/use-theme';
import { questionBank } from '@/lib/mock/demo';
import { formatDuration } from '@/lib/format';
import type { EvidenceNode, InterviewRound, InterviewSession } from '@/lib/types';

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

function sessionMeta(session: InterviewSession): { enableCode: boolean } {
  return { enableCode: (session as unknown as { enableCodeExecution?: boolean }).enableCodeExecution ?? true };
}

function trackForRound(
  round: InterviewRound | undefined,
  phase: 'idle' | 'streaming' | 'error',
  stage: string | null,
  reqHint?: string,
): EvidenceNode[] {
  const hasClaim = Boolean(round?.resumeProbe?.skills?.length);
  const hasReq = Boolean(round?.targetRequirementId);
  const isStreaming = phase === 'streaming';
  const progressing = isStreaming && (stage === 'received' || stage === 'evaluating' || stage === 'feedback');
  const concluding = isStreaming && (stage === 'deciding');
  return [
    {
      key: 'claim',
      label: '简历声明',
      state: hasClaim ? 'verifying' : 'pending',
      hint: round?.resumeProbe?.skills?.[0],
    },
    {
      key: 'requirement',
      label: 'JD 要求',
      state: hasReq ? 'verifying' : 'pending',
      hint: reqHint,
    },
    {
      key: 'question',
      label: '当前问题',
      state: 'proven',
      hint: round ? CATEGORY_LABEL[round.category] ?? round.category : undefined,
    },
    {
      key: 'answer',
      label: '回答证据',
      state: progressing ? 'verifying' : concluding ? 'proven' : 'pending',
      hint: isStreaming ? '正在核对你的回答' : round?.candidateAnswers?.length ? '等待进一步回答' : '等待你的回答',
    },
    {
      key: 'conclusion',
      label: '能力结论',
      state: concluding ? 'verifying' : 'pending',
      hint: undefined,
    },
  ];
}

export function Session() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { isDark } = useTheme();
  const { data: session, isPending } = useSession(id);
  const { data: jobs = [] } = useJobs();
  const { phase, stage, stageText, submitAnswer, submitCode, runSample } = useInterviewFlow(id);

  const [answer, setAnswer] = useState('');
  const [codeByRound, setCodeByRound] = useState<Record<string, string>>({});
  const [abortOpen, setAbortOpen] = useState(false);
  const [, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const activeRound = useMemo(() => {
    if (!session?.rounds?.length) return undefined;
    return session.rounds.find((r) => r.status !== 'evaluated') ?? session.rounds[session.rounds.length - 1];
  }, [session]);

  const bank = activeRound ? questionBank.find((q) => q.id === activeRound.questionId) : undefined;
  const job = jobs.find((j) => j.id === session?.job?.id);
  const targetReq = job?.extraction?.requirements.find(
    (r) => r.requirementId === activeRound?.targetRequirementId,
  );

  const isCoding = activeRound?.questionType === 'coding';
  const codeLanguage = bank?.coding?.language ?? 'go';
  const starterCode = bank?.coding?.starterCode ?? '';
  const currentCode = activeRound ? (codeByRound[activeRound.id] ?? starterCode) : '';

  const lastEvaluated = useMemo(() => {
    if (!session?.rounds?.length) return undefined;
    return [...session.rounds].reverse().find((r) => r.status === 'evaluated');
  }, [session]);

  const track = trackForRound(activeRound, phase, stage, targetReq?.text);

  const elapsedSeconds = session?.startedAt
    ? Math.max(0, Math.floor((Date.now() - new Date(session.startedAt).getTime()) / 1000))
    : 0;

  const handleSubmitAnswer = () => {
    if (!answer.trim()) {
      toast('warning', '回答内容为空', '请先写下你的回答，再提交评估。');
      return;
    }
    submitAnswer.mutate(answer, {
      onSuccess: () => setAnswer(''),
      onError: (err) => toast('error', '提交失败', err.message),
    });
  };

  const handleRunSample = () => {
    if (!activeRound) return;
    runSample.mutate(
      { roundId: activeRound.id, language: codeLanguage, sourceCode: currentCode },
      { onError: (err) => toast('error', '运行失败', err.message) },
    );
  };

  const handleSubmitCode = () => {
    if (!activeRound) return;
    submitCode.mutate(
      { roundId: activeRound.id, language: codeLanguage, sourceCode: currentCode },
      {
        onSuccess: (result) => {
          if (result.outcome.type === 'completed') navigate(`/report/${session?.id}`);
        },
        onError: (err) => toast('error', '提交失败', err.message),
      },
    );
  };

  const handleAbort = () => {
    navigate('/records');
    toast('info', '面试已中止', '可在面试记录中重新进入。');
  };

  // 离开未完成面试时确认
  const shouldBlock = useCallback(
    () =>
      Boolean(session) &&
      !['completed', 'aborted'].includes(session?.status ?? '') &&
      phase === 'idle',
    [session, phase],
  );
  const blocker = useBlocker(shouldBlock);

  // 已完成 → 报告；中止 → 记录页（必须在所有 hooks 之后）
  if (session?.status === 'completed') return <Navigate to={`/report/${session.id}`} replace />;
  if (session?.status === 'aborted') return <Navigate to="/records" replace />;

  if (isPending) return <Loading />;
  if (!session) return <Loading label="面试不存在或已删除…" />;

  const meta = sessionMeta(session);
  const followup = activeRound?.followupQuestions[activeRound.followupQuestions.length - 1];
  const followupOrder = activeRound?.followupCount ?? 0;
  const runResult = runSample.data;

  return (
    <div>
      {/* 页内顶栏：进度 · 计时 · 难度 */}
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <div className="font-mono text-lg font-semibold mono-num">
          {session.currentRoundSequence || 1}
          <span className="text-sm text-ink-tertiary"> / {session.maxQuestions}</span>
        </div>
        <span className="flex items-center gap-1.5 font-mono text-sm text-ink-secondary mono-num">
          <Clock3 className="size-3.5 text-ink-tertiary" />
          {formatDuration(elapsedSeconds)}
        </span>
        {activeRound && (
          <div className="flex items-center gap-1.5">
            <Badge tone="accent">{CATEGORY_LABEL[activeRound.category] ?? activeRound.category}</Badge>
            <Badge>{DIFFICULTY_LABEL[activeRound.difficulty] ?? activeRound.difficulty}</Badge>
            <Tag>{activeRound.topic === 'algorithms' ? '算法' : activeRound.topic}</Tag>
          </div>
        )}
        <div className="ml-auto">
          <Button variant="ghost" size="sm" onClick={() => setAbortOpen(true)}>
            <CircleStop className="size-3.5" /> 结束面试
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        {/* 左列：问题 + 移动端上下文 + 作答区 */}
        <div className="min-w-0 space-y-5">
          {/* 题目卡 */}
          <Panel>
            <PanelHeader
              eyebrow={activeRound ? `QUESTION · ${String(activeRound.sequence).padStart(2, '0')}` : undefined}
              title={activeRound ? `技术主题：${activeRound.topic}` : '准备中'}
              action={isCoding ? <Badge tone="accent" dot>算法题</Badge> : undefined}
            />
            <PanelBody>
              {followup && followupOrder > 0 && (
                <div className="mb-3 flex items-start gap-2.5 rounded border border-warn/30 bg-warn-dim/40 px-3 py-2.5">
                  <MessageSquareText className="mt-0.5 size-4 shrink-0 text-warn" />
                  <div>
                    <div className="text-xs font-medium text-warn">面试官追问（第 {followupOrder} 次）</div>
                    <div className="mt-0.5 text-sm leading-6 text-ink">{followup.question}</div>
                  </div>
                </div>
              )}
              <p className="text-[15px] leading-7 text-ink">{activeRound?.questionText}</p>
              {targetReq && (
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3 text-xs text-ink-secondary">
                  <span className="micro-label shrink-0">本题将验证</span>
                  <span className="min-w-0 flex-1">{targetReq.text}</span>
                  <span className="font-mono text-[10px] text-ink-tertiary">权重 {Math.round(targetReq.weight * 100)}%</span>
                </div>
              )}
            </PanelBody>
          </Panel>

          {/* 移动端上下文（含证据轨道） */}
          <aside className="space-y-4 lg:hidden">
            <ContextPanel
              session={session}
              round={activeRound}
              targetReqText={targetReq?.text}
              track={track}
              phase={phase}
              stageText={stageText}
              lastEvaluated={lastEvaluated}
            />
          </aside>

          {/* 历史回答 */}
          {activeRound && activeRound.candidateAnswers.length > 0 && (
            <Panel>
              <PanelHeader title="本回答记录" />
              <PanelBody className="space-y-3">
                {activeRound.candidateAnswers.map((candidate, index) => (
                  <div key={index} className="flex items-start gap-2.5">
                    <Badge>{candidate.kind === 'initial' ? '首答' : `追问${index}`}</Badge>
                    <p className="min-w-0 flex-1 whitespace-pre-wrap text-sm leading-6 text-ink-secondary">
                      {candidate.answer}
                    </p>
                  </div>
                ))}
              </PanelBody>
            </Panel>
          )}

          {/* 作答区 */}
          {activeRound ? (
            isCoding ? (
              <Panel>
                <PanelHeader
                  eyebrow="CODE EDITOR"
                  title={bank?.coding?.hint ?? '在编辑器中实现你的解法'}
                  action={
                    <div className="flex items-center gap-1.5">
                      <Button size="sm" variant="secondary" disabled={phase === 'streaming' || !meta.enableCode} onClick={handleRunSample}>
                        {runSample.isPending ? <Spinner className="size-3.5" /> : <Play className="size-3.5" />}
                        运行样例
                      </Button>
                      <Button size="sm" variant="primary" disabled={phase === 'streaming'} onClick={handleSubmitCode}>
                        {submitCode.isPending ? <Spinner className="size-3.5" /> : <Send className="size-3.5" />}
                        提交代码
                      </Button>
                    </div>
                  }
                />
                <div className="border-t border-line">
                  <Editor
                    key={activeRound.id}
                    height="320px"
                    language={codeLanguage}
                    theme={isDark ? 'vs-dark' : 'light'}
                    value={currentCode}
                    onChange={(value) =>
                      setCodeByRound((prev) => ({ ...prev, [activeRound.id]: value ?? '' }))
                    }
                    options={{
                      minimap: { enabled: false },
                      fontSize: 13,
                      lineNumbers: 'on',
                      scrollBeyondLastLine: false,
                      wordWrap: 'on',
                      tabSize: 4,
                      automaticLayout: true,
                      padding: { top: 12, bottom: 12 },
                      scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
                    }}
                  />
                </div>
                {!meta.enableCode && (
                  <PanelBody>
                    <div className="text-xs text-ink-tertiary">代码执行已在本场面试中关闭，仅可编辑与提交代码。</div>
                  </PanelBody>
                )}
                {bank?.coding && (
                  <PanelBody className="border-t border-line">
                    <div className="mb-2 flex items-center gap-1.5 text-xs text-ink-secondary">
                      <FileCode2 className="size-3.5" /> 可见样例（{bank.coding.visibleTests.length} 项）与隐藏用例（{bank.coding.hiddenTotal} 项）
                    </div>
                    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                      {bank.coding.visibleTests.map((test, index) => {
                        const result = runResult?.visibleTestResults[index];
                        return (
                          <div key={index} className="flex items-center justify-between gap-2 rounded border border-line bg-surface px-2.5 py-1.5 text-xs">
                            <span className="truncate font-mono text-ink-secondary">{test.name}</span>
                            {result ? (
                              <Badge tone={result.passed ? 'ok' : 'err'}>{result.passed ? '通过' : '失败'}</Badge>
                            ) : (
                              <span className="font-mono text-[10px] text-ink-tertiary">未运行</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </PanelBody>
                )}
              </Panel>
            ) : (
              <Panel>
                <PanelHeader eyebrow="YOUR ANSWER" title="你的回答" />
                <PanelBody>
                  <textarea
                    value={answer}
                    onChange={(event) => setAnswer(event.target.value)}
                    rows={8}
                    placeholder="尽量结构化作答：先给结论，再展开关键点，最后补一个例子。追问时会基于你的回答继续深挖。"
                    className="w-full resize-y rounded border border-line bg-surface px-3 py-2 text-sm leading-6 text-ink placeholder:text-ink-tertiary focus:border-accent focus:outline-none"
                  />
                  <div className="mt-3 flex items-center justify-between">
                    <span className="font-mono text-[11px] text-ink-tertiary mono-num">{answer.length} 字</span>
                    <Button
                      variant="primary"
                      disabled={phase === 'streaming' || !answer.trim()}
                      onClick={handleSubmitAnswer}
                    >
                      {submitAnswer.isPending ? <Spinner className="size-4" /> : <Send className="size-4" />}
                      提交回答
                    </Button>
                  </div>
                </PanelBody>
              </Panel>
            )
          ) : (
            <Panel>
              <PanelBody className="flex items-center gap-3 py-10 text-sm text-ink-secondary">
                <Spinner className="size-4" /> 正在准备第一道题…
              </PanelBody>
            </Panel>
          )}
        </div>

        {/* 右列：上下文（桌面端） */}
        <aside className="hidden lg:block">
          <div className="sticky top-6 space-y-4">
            <ContextPanel
              session={session}
              round={activeRound}
              targetReqText={targetReq?.text}
              track={track}
              phase={phase}
              stageText={stageText}
              lastEvaluated={lastEvaluated}
            />
          </div>
        </aside>
      </div>

      <ConfirmDialog
        open={abortOpen}
        onClose={() => setAbortOpen(false)}
        onConfirm={handleAbort}
        title="结束本场面试？"
        description="尚未作答完成的题目将不会被评估，本场不生成报告。可稍后重新开始一场面试。"
        confirmText="结束面试"
        danger
      />

      <ConfirmDialog
        open={blocker?.state === 'blocked'}
        onClose={() => {
          blocker?.reset?.();
        }}
        onConfirm={() => {
          blocker?.proceed?.();
        }}
        title="离开未完成的面试？"
        description="面试进度已自动保存，可随时返回继续。确定要离开吗？"
        confirmText="离开"
      />
    </div>
  );
}

function ContextPanel({
  session,
  round,
  targetReqText,
  track,
  phase,
  stageText,
  lastEvaluated,
}: {
  session: InterviewSession;
  round?: InterviewRound;
  targetReqText?: string;
  track: EvidenceNode[];
  phase: 'idle' | 'streaming' | 'error';
  stageText: string | null;
  lastEvaluated?: InterviewRound;
}) {
  const isFollowup = (round?.followupCount ?? 0) > 0;
  const claim = round?.resumeProbe?.skills?.[0];
  return (
    <>
      <Panel>
        <PanelHeader title="本题为什么被选择" eyebrow="CONTEXT" />
        <PanelBody className="space-y-3 text-sm leading-6 text-ink-secondary">
          {round?.questionReason ? (
            <p>{round.questionReason}</p>
          ) : (
            <p className="text-ink-tertiary">回答后，面试官会根据你的内容决定下一步。</p>
          )}
        </PanelBody>
      </Panel>

      <Panel>
        <PanelHeader title="当前证据轨道" eyebrow="EVIDENCE" />
        <PanelBody>
          <EvidenceTrack
            nodes={track}
            streaming={phase === 'streaming'}
            streamingText={stageText}
          />
        </PanelBody>
      </Panel>

      <Panel>
        <PanelHeader title="验证上下文" eyebrow="SOURCE" />
        <PanelBody className="space-y-3.5">
          <div>
            <div className="micro-label mb-1.5">正在验证的 JD 要求</div>
            {targetReqText ? (
              <div className="text-sm leading-6 text-ink-secondary">{targetReqText}</div>
            ) : (
              <div className="text-xs text-ink-tertiary">本题未关联具体 JD 要求</div>
            )}
          </div>
          <div>
            <div className="micro-label mb-1.5">对应的简历声明</div>
            {claim ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone="warn" dot>{claim}</Badge>
                {round?.resumeProbe?.project && (
                  <span className="text-xs text-ink-tertiary">项目：{round.resumeProbe.project.name}</span>
                )}
              </div>
            ) : (
              <div className="text-xs text-ink-tertiary">本题不针对具体简历声明</div>
            )}
          </div>
          <div>
            <div className="micro-label mb-1.5">本轮性质</div>
            {isFollowup ? (
              <Badge tone="accent" dot>第 {round?.followupCount} 次追问</Badge>
            ) : (
              <Badge>首次作答</Badge>
            )}
          </div>
        </PanelBody>
      </Panel>

      <Panel>
        <PanelHeader title="面试进度" eyebrow="PROGRESS" />
        <PanelBody>
          <div className="mb-2 flex items-center justify-between font-mono text-xs text-ink-secondary mono-num">
            <span>{session.completedQuestionCount} 已答</span>
            <span>{session.currentRoundSequence}/{session.maxQuestions} 题</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-500"
              style={{ width: `${(session.completedQuestionCount / session.maxQuestions) * 100}%` }}
            />
          </div>
        </PanelBody>
      </Panel>

      {lastEvaluated && (
        <Panel>
          <PanelHeader title="上一题评估" eyebrow="FEEDBACK" />
          <PanelBody className="space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm text-ink mono-num">
                {lastEvaluated.score?.toFixed(1)}<span className="text-xs text-ink-tertiary"> / 5</span>
              </span>
              <VerdictBadge verdict={lastEvaluated.verdict} />
            </div>
            {lastEvaluated.evaluationSummary && (
              <div className="font-mono text-[11px] text-ink-tertiary">{lastEvaluated.evaluationSummary}</div>
            )}
            {lastEvaluated.feedback && (
              <p className="text-sm leading-6 text-ink-secondary">{lastEvaluated.feedback}</p>
            )}
            {lastEvaluated.weakPoint && (
              <div className="flex items-start gap-2 text-xs text-warn">
                <AlarmClock className="mt-0.5 size-3.5 shrink-0" />
                {lastEvaluated.weakPoint}
              </div>
            )}
          </PanelBody>
        </Panel>
      )}
    </>
  );
}

function VerdictBadge({ verdict }: { verdict?: string }) {
  if (verdict === 'pass') return <Badge tone="ok" dot>通过</Badge>;
  if (verdict === 'partial') return <Badge tone="warn" dot>部分通过</Badge>;
  if (verdict === 'fail') return <Badge tone="err" dot>未通过</Badge>;
  return <Badge>—</Badge>;
}
