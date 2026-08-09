import Editor from '@monaco-editor/react';
import { Button } from '@/components/ui/button';
import {
  CsInterviewKeys,
  useInterviewMutations,
  useInterviewSession,
} from '@/hooks/use-cs-interview-request';
import {
  InterviewSession as InterviewSessionType,
  InterviewStreamEvent,
} from '@/interfaces/database/cs-interview';
import { Routes } from '@/routes';
import { submitInterviewAnswer } from '@/services/cs-interview-service';
import { useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Code2,
  Database,
  Loader2,
  Play,
  RotateCcw,
  Send,
  StopCircle,
} from 'lucide-react';
import {
  ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import { useNavigate, useParams } from 'react-router';
import { InterviewShell, StatusPill } from './components';

type StreamState = 'idle' | 'answer_received' | 'evaluating' | 'disconnected';

const InitialCode = {
  python:
    'import json\n\ndef solve(value):\n    return value\n\nprint(json.dumps(solve(json.loads(input()))))\n',
  go: 'package main\n\nimport (\n  "encoding/json"\n  "fmt"\n  "os"\n)\n\nfunc main() {\n  var value any\n  _ = json.NewDecoder(os.Stdin).Decode(&value)\n  output, _ := json.Marshal(value)\n  fmt.Println(string(output))\n}\n',
  javascript:
    'const fs = require("fs");\nconst value = JSON.parse(fs.readFileSync(0, "utf8"));\nfunction solve(input) {\n  return input;\n}\nconsole.log(JSON.stringify(solve(value)));\n',
};

export default function InterviewSessionPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {
    data: session,
    isLoading,
    isError,
    refetch,
  } = useInterviewSession(id);
  const { runCode, submitCode, abortSession } = useInterviewMutations();
  const [answer, setAnswer] = useState('');
  const [streamState, setStreamState] = useState<StreamState>('idle');
  const [streamMessage, setStreamMessage] = useState<string>();
  const [language, setLanguage] = useState<'python' | 'go' | 'javascript'>(
    'python',
  );
  const [sourceCode, setSourceCode] = useState(InitialCode.python);
  const [codeResult, setCodeResult] = useState<any>();
  const [elapsed, setElapsed] = useState(0);
  const retryRef = useRef<{
    requestId: string;
    answer: string;
    stateVersion: number;
  }>();

  useEffect(() => {
    if (!session?.startedAt || session.status === 'completed') return;
    const updateElapsed = () =>
      setElapsed(Math.max(0, dayjs().diff(dayjs(session.startedAt), 'second')));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [session?.startedAt, session?.status]);

  useEffect(() => {
    setSourceCode(InitialCode[language]);
    setCodeResult(undefined);
  }, [language]);

  const handleStreamEvent = useCallback(
    (event: InterviewStreamEvent) => {
      if (event.event === 'answer_received' || event.event === 'evaluating') {
        setStreamState(event.event);
      }
      if (event.event === 'feedback') {
        setStreamMessage(event.data.feedback);
      }
      if (event.event === 'next_question' && event.data.session) {
        queryClient.setQueryData(
          CsInterviewKeys.session(id),
          event.data.session as InterviewSessionType,
        );
        setAnswer('');
        setStreamState('idle');
        setStreamMessage(undefined);
        setCodeResult(undefined);
      }
      if (event.event === 'followup_question') {
        setStreamState('idle');
      }
      if (event.event === 'interview_completed') {
        navigate(`${Routes.CsInterviewReport}/${id}`);
      }
      if (event.event === 'error') {
        setStreamState('disconnected');
        setStreamMessage(event.data.message);
      }
    },
    [id, navigate, queryClient],
  );

  const sendAnswer = async (payload: {
    requestId: string;
    answer: string;
    stateVersion: number;
  }) => {
    setStreamState('answer_received');
    setStreamMessage(undefined);
    try {
      await submitInterviewAnswer(id, payload, handleStreamEvent);
      await refetch();
    } catch (reason) {
      setStreamState('disconnected');
      setStreamMessage(
        reason instanceof Error
          ? reason.message
          : t('csInterview.session.networkError'),
      );
    }
  };
  const handleAnswerChange = (event: ChangeEvent<HTMLTextAreaElement>) =>
    setAnswer(event.target.value);
  const handleSubmitAnswer = async () => {
    if (!session || !answer.trim()) return;
    const payload = {
      requestId: crypto.randomUUID(),
      answer: answer.trim(),
      stateVersion: session.stateVersion,
    };
    retryRef.current = payload;
    await sendAnswer(payload);
  };
  const handleRetry = async () => {
    if (retryRef.current) await sendAnswer(retryRef.current);
    else await refetch();
  };
  const handleLanguageChange = (event: ChangeEvent<HTMLSelectElement>) =>
    setLanguage(event.target.value as typeof language);
  const handleCodeChange = (value?: string) => setSourceCode(value || '');
  const handleRunCode = async () => {
    setCodeResult(await runCode.mutateAsync({ id, language, sourceCode }));
  };
  const handleSubmitCode = async () => {
    setCodeResult(await submitCode.mutateAsync({ id, language, sourceCode }));
    await refetch();
  };
  const handleAbort = async () => {
    if (!session || !window.confirm(t('csInterview.session.abortConfirm')))
      return;
    await abortSession.mutateAsync({ id, stateVersion: session.stateVersion });
    navigate(Routes.CsInterview);
  };

  const timer = useMemo(() => {
    const minutes = Math.floor(elapsed / 60)
      .toString()
      .padStart(2, '0');
    const seconds = (elapsed % 60).toString().padStart(2, '0');
    return `${minutes}:${seconds}`;
  }, [elapsed]);

  if (isLoading)
    return (
      <InterviewShell>
        <div className="flex h-64 items-center justify-center text-text-secondary">
          <Loader2 className="mr-2 animate-spin" />
          {t('csInterview.loading')}
        </div>
      </InterviewShell>
    );
  if (isError || !session)
    return (
      <InterviewShell>
        <div className="border border-state-error bg-state-error-5 p-6 text-state-error">
          {t('csInterview.session.loadError')}
        </div>
      </InterviewShell>
    );
  const round = session.activeRound;
  const coding = round?.category === 'leetcode';
  const followup =
    round?.followupQuestions?.[round.followupQuestions.length - 1];
  const busy =
    streamState === 'answer_received' || streamState === 'evaluating';
  return (
    <InterviewShell>
      <header className="mb-8 flex flex-wrap items-center gap-4 border-b border-border-button pb-6">
        <div className="mr-auto">
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-secondary">
            {t('csInterview.session.live')}
          </div>
          <h1 className="mt-2 text-xl font-semibold">
            {t('csInterview.session.title')}
          </h1>
        </div>
        <StatusPill status={session.status} />
        <div className="flex items-center gap-2 font-mono text-sm">
          <Clock3 className="size-4 text-text-secondary" />
          {timer}
        </div>
        <Button variant="danger" onClick={handleAbort}>
          <StopCircle />
          {t('csInterview.session.abort')}
        </Button>
      </header>
      <div className="mb-8">
        <div className="mb-2 flex justify-between font-mono text-[10px] uppercase tracking-wider text-text-secondary">
          <span>
            {t('csInterview.session.progress', {
              current: round?.sequence || session.currentRoundSequence,
              total: session.maxQuestions,
            })}
          </span>
          <span>{session.currentDifficulty}</span>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-bg-card">
          <div
            className="h-full bg-accent-primary transition-[width]"
            style={{
              width: `${Math.max(4, ((round?.sequence || 1) / session.maxQuestions) * 100)}%`,
            }}
          />
        </div>
      </div>
      {!round ? (
        <div className="border border-state-warning bg-state-warning-5 p-6">
          {t('csInterview.session.noActiveRound')}
        </div>
      ) : (
        <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_300px]">
          <div className="min-w-0">
            <section className="border-l-2 border-text-primary pl-5 sm:pl-7">
              <div className="mb-3 flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-text-secondary">
                <span>{round.category}</span>
                <span>·</span>
                <span>{round.topic}</span>
                <span>·</span>
                <span>{round.difficulty}</span>
              </div>
              <div className="mb-5 border border-border-button bg-bg-card p-4 text-xs leading-5 text-text-secondary">
                <div className="font-medium text-text-primary">
                  {round.selectedAction} · {round.targetRequirement?.text ?? round.targetRequirementId}
                </div>
                {round.questionReason && <p className="mt-1">{round.questionReason}</p>}
                {round.resumeProbe && (
                  <p className="mt-1">
                    简历声明：{round.resumeProbe.skills.join('、') || '相关项目经历'}
                    {round.resumeProbe.project?.name ? ` · ${round.resumeProbe.project.name}` : ''}
                  </p>
                )}
              </div>
              <div className="prose max-w-none text-text-primary prose-p:leading-8 dark:prose-invert">
                <ReactMarkdown>
                  {followup?.question || round.questionText}
                </ReactMarkdown>
              </div>
              {followup && (
                <div className="mt-4 text-xs text-text-secondary">
                  {t('csInterview.session.followupCount', {
                    current: round.followupCount,
                    total: session.maxFollowups,
                  })}
                </div>
              )}
            </section>
            {coding && (
              <section className="mt-8 overflow-hidden border border-border-button">
                <div className="flex items-center gap-3 border-b border-border-button bg-bg-card px-4 py-3">
                  <Code2 className="size-4" />
                  <span className="text-sm font-medium">
                    {t('csInterview.session.codeEditor')}
                  </span>
                  <select
                    value={language}
                    onChange={handleLanguageChange}
                    className="ml-auto rounded border border-border-button bg-bg-input px-2 py-1 text-xs"
                  >
                    <option value="python">Python</option>
                    <option value="go">Go</option>
                    <option value="javascript">JavaScript</option>
                  </select>
                </div>
                <Editor
                  height="360px"
                  language={language === 'javascript' ? 'javascript' : language}
                  value={sourceCode}
                  onChange={handleCodeChange}
                  theme="vs-dark"
                  options={{
                    minimap: { enabled: false },
                    fontSize: 13,
                    wordWrap: 'on',
                    automaticLayout: true,
                  }}
                />
                <div className="flex flex-wrap items-center gap-3 border-t border-border-button p-3">
                  <Button
                    variant="outline"
                    onClick={handleRunCode}
                    loading={runCode.isPending}
                  >
                    <Play />
                    {t('csInterview.session.runSamples')}
                  </Button>
                  <Button
                    onClick={handleSubmitCode}
                    loading={submitCode.isPending}
                  >
                    {t('csInterview.session.submitCode')}
                  </Button>
                  {codeResult && (
                    <span className="ml-auto font-mono text-xs text-text-secondary">
                      {codeResult.passedCount}/{codeResult.totalCount} ·{' '}
                      {codeResult.runtimeMs}ms
                    </span>
                  )}
                </div>
                {codeResult?.compilerOutput && (
                  <pre className="max-h-32 overflow-auto border-t border-border-button bg-bg-card p-3 text-xs text-state-error">
                    {codeResult.compilerOutput}
                  </pre>
                )}
              </section>
            )}
            <section className="mt-8">
              <label
                className="mb-3 block text-sm font-medium"
                htmlFor="interview-answer"
              >
                {t('csInterview.session.yourAnswer')}
              </label>
              <textarea
                id="interview-answer"
                value={answer}
                onChange={handleAnswerChange}
                disabled={busy}
                maxLength={20000}
                className="min-h-44 w-full resize-y rounded-md border border-border-button bg-bg-input p-4 text-sm leading-7 outline-none focus:ring-1 focus:ring-accent-primary disabled:opacity-60"
                placeholder={t('csInterview.session.answerPlaceholder')}
              />
              <div className="mt-3 flex items-center justify-between gap-4">
                <span className="text-xs text-text-secondary">
                  {answer.length}/20000
                </span>
                <Button
                  size="lg"
                  onClick={handleSubmitAnswer}
                  disabled={!answer.trim() || busy}
                >
                  <Send />
                  {t('csInterview.session.submitAnswer')}
                </Button>
              </div>
            </section>
          </div>
          <aside className="space-y-5">
            <section className="border border-border-button p-5">
              <h2 className="mb-4 flex items-center gap-2 text-sm font-medium">
                <Database className="size-4 text-text-secondary" />
                {t('csInterview.session.evidence')}
              </h2>
              <div className="space-y-4">
                {round.evidenceSources.map((source) => (
                  <div
                    key={source.evidenceId}
                    className="border-l border-border-default pl-3 text-xs leading-5"
                  >
                    <div className="font-medium">
                      {source.documentName || t('csInterview.session.source')}
                    </div>
                    <div className="text-text-secondary">
                      {source.sourceDate ||
                        t('csInterview.session.verifiedSource')}
                    </div>
                  </div>
                ))}
              </div>
            </section>
            <section
              className="border border-border-button p-5"
              aria-live="polite"
            >
              <h2 className="mb-3 text-sm font-medium">
                {t('csInterview.session.runtime')}
              </h2>
              {streamState === 'idle' && (
                <p className="text-sm text-text-secondary">
                  {t('csInterview.session.waiting')}
                </p>
              )}
              {busy && (
                <p className="flex items-center gap-2 text-sm">
                  <Loader2 className="size-4 animate-spin" />
                  {t(`csInterview.session.${streamState}`)}
                </p>
              )}
              {streamState === 'disconnected' && (
                <div className="space-y-3 text-sm text-state-error">
                  <p className="flex gap-2">
                    <AlertCircle className="mt-0.5 size-4 shrink-0" />
                    {streamMessage || t('csInterview.session.networkError')}
                  </p>
                  <Button variant="outline" onClick={handleRetry}>
                    <RotateCcw />
                    {t('csInterview.session.retry')}
                  </Button>
                </div>
              )}
              {streamMessage && streamState !== 'disconnected' && (
                <p className="flex gap-2 text-sm leading-6 text-text-secondary">
                  <CheckCircle2 className="mt-1 size-4 shrink-0 text-state-success" />
                  {streamMessage}
                </p>
              )}
            </section>
          </aside>
        </div>
      )}
    </InterviewShell>
  );
}
