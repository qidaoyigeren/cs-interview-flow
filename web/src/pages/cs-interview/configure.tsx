import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  useInterviewKnowledgeConfig,
  useInterviewJobs,
  useInterviewMutations,
  useInterviewResumes,
} from '@/hooks/use-cs-interview-request';
import { InterviewStreamEvent } from '@/interfaces/database/cs-interview';
import { InterviewProfilePayload } from '@/interfaces/request/cs-interview';
import { startInterview } from '@/services/cs-interview-service';
import { Routes } from '@/routes';
import {
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  Database,
  FileText,
  ShieldAlert,
} from 'lucide-react';
import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';
import {
  InterviewShell,
  NativeSelectThemeClass,
  PageHeading,
  SectionTitle,
} from './components';
import { validateInterviewConfiguration } from './validation';

const InitialProfile: InterviewProfilePayload = {
  name: '下一场技术面试',
  targetRole: 'go_backend',
  targetLevel: 'mid',
  technologyStack: ['Go', 'MySQL', 'Redis'],
  focusTopics: [],
  excludedTopics: [],
  initialDifficulty: 'medium',
  preferredCategories: ['interview_experience', 'leetcode', 'baguwen'],
  questionCount: 8,
  maxFollowups: 2,
  resumeId: '',
  jobId: '',
};

const parseList = (value: string) =>
  value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);

type ListField = 'technologyStack' | 'focusTopics' | 'excludedTopics';

const InitialListValues: Record<ListField, string> = {
  technologyStack: InitialProfile.technologyStack.join(', '),
  focusTopics: InitialProfile.focusTopics.join(', '),
  excludedTopics: InitialProfile.excludedTopics.join(', '),
};

type RequestError = {
  response?: { data?: { message?: unknown } };
};

const requestErrorMessage = (error: unknown, fallback: string) => {
  const serverMessage = (error as RequestError)?.response?.data?.message;
  if (typeof serverMessage === 'string' && serverMessage.trim()) {
    return serverMessage;
  }
  return error instanceof Error ? error.message : fallback;
};

export default function InterviewConfigure() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: knowledge, isLoading: knowledgeLoading } =
    useInterviewKnowledgeConfig();
  const { data: resumes = [] } = useInterviewResumes();
  const { data: jobs = [] } = useInterviewJobs();
  const { createProfile, createSession } = useInterviewMutations();
  const [profile, setProfile] = useState(InitialProfile);
  const [listValues, setListValues] = useState(InitialListValues);
  const [formError, setFormError] = useState<string>();
  const [starting, setStarting] = useState(false);
  const selectableResumes = useMemo(
    () =>
      resumes.filter(
        (item) =>
          item.parseStatus === 'parsed' &&
          Boolean(item.extraction) &&
          !item.needsExtraction,
      ),
    [resumes],
  );
  const selectableJobs = useMemo(
    () => jobs.filter((item) => Boolean(item.extraction)),
    [jobs],
  );
  const selectableResumeIds = useMemo(
    () => new Set(selectableResumes.map((item) => item.id)),
    [selectableResumes],
  );
  const selectableJobIds = useMemo(
    () => new Set(selectableJobs.map((item) => item.id)),
    [selectableJobs],
  );

  useEffect(() => {
    setProfile((current) => {
      const resumeId = selectableResumeIds.has(current.resumeId)
        ? current.resumeId
        : '';
      const jobId = selectableJobIds.has(current.jobId) ? current.jobId : '';
      return resumeId === current.resumeId && jobId === current.jobId
        ? current
        : { ...current, resumeId, jobId };
    });
  }, [selectableJobIds, selectableResumeIds]);

  const handleTextChange = (
    event: ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => {
    const field = event.target.name;
    setProfile((current) => ({ ...current, [field]: event.target.value }));
  };
  const handleNumberChange = (event: ChangeEvent<HTMLInputElement>) => {
    const field = event.target.name;
    setProfile((current) => ({
      ...current,
      [field]: Number(event.target.value),
    }));
  };
  const handleListChange = (event: ChangeEvent<HTMLInputElement>) => {
    const field = event.target.name as ListField;
    const value = event.target.value;
    setListValues((current) => ({ ...current, [field]: value }));
    setProfile((current) => ({
      ...current,
      [field]: parseList(value),
    }));
  };
  const handleStartEvent = (event: InterviewStreamEvent) => {
    if (event.event === 'next_question') {
      const sessionId = event.data.session?.id;
      if (sessionId) navigate(`${Routes.CsInterviewSession}/${sessionId}`);
    }
    if (event.event === 'error') setFormError(event.data.message);
  };
  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const errors = validateInterviewConfiguration(profile, knowledge);
    if (!selectableResumeIds.has(profile.resumeId)) errors.push('resumeId');
    if (!selectableJobIds.has(profile.jobId)) errors.push('jobId');
    if (errors.length) {
      const errorKey = errors.includes('topicConflict')
        ? 'csInterview.configure.topicConflict'
        : errors.includes('resumeId')
          ? 'csInterview.configure.resumeUnavailable'
          : errors.includes('jobId')
            ? 'csInterview.configure.jobUnavailable'
            : 'csInterview.configure.validationError';
      setFormError(
        t(errorKey),
      );
      return;
    }
    setStarting(true);
    setFormError(undefined);
    try {
      const savedProfile = await createProfile.mutateAsync(profile);
      const session = await createSession.mutateAsync({
        profileId: savedProfile.id,
        knowledgeConfigId: knowledge!.id,
      });
      await startInterview(
        session.id,
        { requestId: crypto.randomUUID(), stateVersion: session.stateVersion },
        handleStartEvent,
      );
    } catch (error) {
      setFormError(
        requestErrorMessage(error, t('csInterview.configure.startError')),
      );
    } finally {
      setStarting(false);
    }
  };

  const selectClass = `h-10 w-full rounded-md border border-border-button bg-bg-input px-3 text-sm outline-none focus:ring-1 focus:ring-accent-primary ${NativeSelectThemeClass}`;
  const inputClass = 'h-10';
  return (
    <InterviewShell>
      <PageHeading
        eyebrow={t('csInterview.configure.eyebrow')}
        title={t('csInterview.configure.title')}
        description={t('csInterview.configure.description')}
      />
      <form onSubmit={handleSubmit} className="max-w-4xl space-y-10">
        <section>
          <SectionTitle icon={BriefcaseBusiness}>候选人与岗位证据</SectionTitle>
          <div className="grid gap-5 sm:grid-cols-2">
            <label className="space-y-2 text-sm">
              <span className="flex items-center gap-2">
                <FileText className="size-4" />
                已抽取简历
              </span>
              <select
                name="resumeId"
                value={profile.resumeId}
                onChange={handleTextChange}
                className={selectClass}
              >
                <option value="">请选择简历</option>
                {resumes.map((resume) => {
                  const selectable = selectableResumeIds.has(resume.id);
                  return (
                    <option
                      key={resume.id}
                      value={resume.id}
                      disabled={!selectable}
                    >
                      {resume.fileName}
                      {selectable
                        ? ''
                        : t('csInterview.configure.resumeNotReady')}
                    </option>
                  );
                })}
              </select>
              <Link
                to={Routes.CsInterviewResumes}
                className="inline-block text-xs text-accent-primary"
              >
                上传或检查简历
              </Link>
            </label>
            <label className="space-y-2 text-sm">
              <span className="flex items-center gap-2">
                <BriefcaseBusiness className="size-4" />
                已检查 JD
              </span>
              <select
                name="jobId"
                value={profile.jobId}
                onChange={handleTextChange}
                className={selectClass}
              >
                <option value="">请选择岗位 JD</option>
                {jobs.map((job) => {
                  const selectable = selectableJobIds.has(job.id);
                  return (
                    <option
                      key={job.id}
                      value={job.id}
                      disabled={!selectable}
                    >
                      {job.name}
                      {selectable
                        ? ''
                        : t('csInterview.configure.jobNotReady')}
                    </option>
                  );
                })}
              </select>
              <Link
                to={Routes.CsInterviewJobs}
                className="inline-block text-xs text-accent-primary"
              >
                上传、粘贴或修正 JD
              </Link>
            </label>
          </div>
        </section>
        <section>
          <SectionTitle>{t('csInterview.configure.position')}</SectionTitle>
          <div className="grid gap-5 sm:grid-cols-2">
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.name')}</span>
              <Input
                name="name"
                value={profile.name}
                onChange={handleTextChange}
                className={inputClass}
              />
            </label>
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.role')}</span>
              <select
                name="targetRole"
                value={profile.targetRole}
                onChange={handleTextChange}
                className={selectClass}
              >
                <option value="go_backend">Go 后端</option>
                <option value="java_backend">Java 后端</option>
                <option value="python_backend">Python 后端</option>
                <option value="frontend">前端</option>
                <option value="ml_engineer">算法工程师</option>
                <option value="ai_backend">大模型应用后端</option>
                <option value="sdet">测试开发</option>
                <option value="cs_general">通用计算机基础</option>
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.level')}</span>
              <select
                name="targetLevel"
                value={profile.targetLevel}
                onChange={handleTextChange}
                className={selectClass}
              >
                <option value="junior">初级</option>
                <option value="mid">中级</option>
                <option value="senior">高级</option>
                <option value="staff">专家</option>
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.stack')}</span>
              <Input
                name="technologyStack"
                value={listValues.technologyStack}
                onChange={handleListChange}
                className={inputClass}
              />
            </label>
          </div>
        </section>
        <section>
          <SectionTitle>{t('csInterview.configure.rules')}</SectionTitle>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.difficulty')}</span>
              <select
                name="initialDifficulty"
                value={profile.initialDifficulty}
                onChange={handleTextChange}
                className={selectClass}
              >
                <option value="beginner">初级</option>
                <option value="medium">中级</option>
                <option value="advanced">高级</option>
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.questions')}</span>
              <Input
                type="number"
                name="questionCount"
                min={1}
                max={20}
                value={profile.questionCount}
                onChange={handleNumberChange}
                className={inputClass}
              />
            </label>
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.followups')}</span>
              <Input
                type="number"
                name="maxFollowups"
                min={0}
                max={5}
                value={profile.maxFollowups}
                onChange={handleNumberChange}
                className={inputClass}
              />
            </label>
          </div>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.focus')}</span>
              <Input
                name="focusTopics"
                value={listValues.focusTopics}
                onChange={handleListChange}
                placeholder="database.mysql, go.runtime"
                className={inputClass}
              />
            </label>
            <label className="space-y-2 text-sm">
              <span>{t('csInterview.configure.exclude')}</span>
              <Input
                name="excludedTopics"
                value={listValues.excludedTopics}
                onChange={handleListChange}
                placeholder="ml.system"
                className={inputClass}
              />
            </label>
          </div>
        </section>
        <section>
          <SectionTitle icon={Database}>
            {t('csInterview.configure.knowledge')}
          </SectionTitle>
          <div className="flex items-start gap-4 border border-border-button bg-bg-card p-5">
            {knowledge?.enabled ? (
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-state-success" />
            ) : (
              <ShieldAlert className="mt-0.5 size-5 shrink-0 text-state-warning" />
            )}
            <div className="min-w-0 flex-1">
              <div className="font-medium">
                {knowledge?.enabled
                  ? t('csInterview.configure.knowledgeReady')
                  : t('csInterview.configure.knowledgeMissing')}
              </div>
              <p className="mt-1 text-sm leading-6 text-text-secondary">
                {knowledgeLoading
                  ? t('csInterview.loading')
                  : t('csInterview.configure.knowledgeDescription')}
              </p>
            </div>
            <Button asLink to={Routes.CsInterviewKnowledge} variant="outline">
              {t('csInterview.configure.manageKnowledge')}
            </Button>
          </div>
        </section>
        {formError && (
          <div
            role="alert"
            className="border-l-2 border-state-error bg-state-error-5 px-4 py-3 text-sm text-state-error"
          >
            {formError}
          </div>
        )}
        <div className="flex items-center justify-between border-t border-border-button pt-6">
          <Link
            to={Routes.CsInterview}
            className="text-sm text-text-secondary hover:text-text-primary"
          >
            {t('common.back')}
          </Link>
          <Button
            type="submit"
            size="lg"
            loading={starting}
            disabled={
              !knowledge?.enabled ||
              !selectableResumeIds.has(profile.resumeId) ||
              !selectableJobIds.has(profile.jobId)
            }
          >
            {t('csInterview.configure.start')}
            <ArrowRight />
          </Button>
        </div>
      </form>
    </InterviewShell>
  );
}
