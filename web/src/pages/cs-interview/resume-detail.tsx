import { Button } from '@/components/ui/button';
import { Routes } from '@/routes';
import {
  useInterviewJobs,
  useInterviewMutations,
  useInterviewResume,
} from '@/hooks/use-cs-interview-request';
import {
  InterviewDifficulty,
  ResumeExtraction,
} from '@/interfaces/database/cs-interview';
import dayjs from 'dayjs';
import { ArrowLeft, RefreshCw, UserPlus } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';
import { toast } from 'sonner';
import {
  InterviewShell,
  NativeSelectThemeClass,
  PageHeading,
  SectionTitle,
} from './components';
import { ResumeStatusPill } from './resumes';

const DEFAULT_ROLES = [
  'go_backend',
  'java_backend',
  'python_backend',
  'frontend',
  'ml_engineer',
  'ai_backend',
  'sdet',
  'cs_general',
];

const DEFAULT_LEVELS = ['junior', 'mid', 'senior', 'staff'];

const initialForm = (extraction?: ResumeExtraction, fallbackName = '') => {
  const focusTopics = [
    ...new Set(
      (extraction?.claimedSkills ?? []).flatMap((skill) => skill.topics ?? []),
    ),
  ];
  return {
    name: extraction?.targetRole ?? fallbackName,
    targetRole: extraction?.targetRole ?? 'cs_general',
    targetLevel: extraction?.targetLevel ?? 'mid',
    technologyStack: (extraction?.technologyStack ?? []).join(', '),
    focusTopics: focusTopics.join(', '),
    initialDifficulty: 'medium',
    questionCount: '8',
    maxFollowups: '2',
    jobId: '',
  };
};

export default function ResumeDetailPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: resume, isLoading } = useInterviewResume(id);
  const { data: jobs = [] } = useInterviewJobs();
  const { extractResume, createProfileFromResume } = useInterviewMutations();
  const [extracting, setExtracting] = useState(false);
  const [form, setForm] = useState(() =>
    initialForm(resume?.extraction, resume?.fileName ?? ''),
  );
  const hydratedResumeKey = useRef('');

  useEffect(() => {
    if (!resume) return;
    const resumeKey = `${resume.id}:${resume.extractedAt ?? 'not-extracted'}`;
    if (hydratedResumeKey.current === resumeKey) return;
    hydratedResumeKey.current = resumeKey;
    setForm(initialForm(resume.extraction, resume.fileName));
  }, [resume]);

  const handleExtract = async () => {
    setExtracting(true);
    try {
      const updated = await extractResume.mutateAsync({ id, force: true });
      setForm(initialForm(updated.extraction, updated.fileName));
      toast.success(updated.fileName);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setExtracting(false);
    }
  };

  const handleCreateProfile = async () => {
    try {
      await createProfileFromResume.mutateAsync({
        id,
        payload: {
          name: form.name.trim() || form.targetRole,
          targetRole: form.targetRole,
          targetLevel: form.targetLevel,
          technologyStack: form.technologyStack
            .split(/[,，]/)
            .map((item) => item.trim())
            .filter(Boolean),
          focusTopics: form.focusTopics
            .split(/[,，]/)
            .map((item) => item.trim())
            .filter(Boolean),
          initialDifficulty: form.initialDifficulty as InterviewDifficulty,
          questionCount: Math.max(
            1,
            Math.min(20, Number(form.questionCount) || 8),
          ),
          maxFollowups: Math.max(
            0,
            Math.min(5, Number(form.maxFollowups) || 2),
          ),
          jobId: form.jobId,
        },
      });
      toast.success(t('csInterview.resumeDetail.saveProfile'));
      navigate(Routes.CsInterviewConfigure);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  const selectClass = `h-10 w-full rounded-md border border-border-button bg-bg-input px-3 text-sm outline-none focus:ring-1 focus:ring-accent-primary ${NativeSelectThemeClass}`;
  const inputClass = 'h-10';

  if (isLoading) {
    return (
      <InterviewShell>
        <div className="h-64 animate-pulse bg-bg-card" />
      </InterviewShell>
    );
  }

  if (!resume) {
    return (
      <InterviewShell>
        <PageHeading
          eyebrow={t('csInterview.resumeDetail.eyebrow')}
          title={t('csInterview.resumeDetail.title')}
          description=""
        />
        <p className="text-sm text-text-secondary">
          {t('csInterview.report.loadError')}
        </p>
      </InterviewShell>
    );
  }

  const extraction = resume.extraction;
  const claimedSkills = extraction?.claimedSkills ?? [];
  const projects = extraction?.projects ?? [];

  return (
    <InterviewShell>
      <PageHeading
        eyebrow={t('csInterview.resumeDetail.eyebrow')}
        title={resume.fileName}
        description={`${t('csInterview.resumeDetail.parseStatus')}: ${t(`csInterview.resumes.status.${resume.parseStatus}`)} · ${resume.chunkCount} ${t('csInterview.resumeDetail.chunks')}${resume.extractedAt ? ` · ${t('csInterview.resumeDetail.extractedAt')}: ${dayjs(resume.extractedAt).format('YYYY-MM-DD HH:mm')}` : ''}`}
        action={
          <Button
            asLink
            to={Routes.CsInterviewResumes}
            variant="outline"
            size="sm"
          >
            <ArrowLeft className="size-4" />
            {t('csInterview.resumeDetail.back')}
          </Button>
        }
      />

      <div className="max-w-5xl space-y-10">
        <section>
          <SectionTitle icon={RefreshCw}>
            {t('csInterview.resumeDetail.profileSummary')}
          </SectionTitle>
          <ResumeStatusPill status={resume.parseStatus} />
          <Button
            variant="outline"
            size="sm"
            className="ml-3"
            onClick={handleExtract}
            disabled={extracting || resume.parseStatus === 'parsing'}
          >
            <RefreshCw className="size-3" />
            {extraction
              ? t('csInterview.resumes.reExtract')
              : t('csInterview.resumes.extract')}
          </Button>

          {resume.needsExtraction && extraction ? (
            <p className="mt-4 border border-state-warning bg-state-warning-5 p-3 text-sm leading-6 text-state-warning">
              {t('csInterview.resumeDetail.outdatedExtraction')}
            </p>
          ) : null}

          {!extraction ? (
            <p className="mt-4 text-sm text-text-secondary">
              {t('csInterview.resumeDetail.noExtraction')}
            </p>
          ) : (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <InfoItem
                label={t('csInterview.resumeDetail.targetRole')}
                value={extraction.targetRole ?? '-'}
              />
              <InfoItem
                label={t('csInterview.resumeDetail.targetLevel')}
                value={extraction.targetLevel ?? '-'}
              />
              <InfoItem
                label={t('csInterview.resumeDetail.technologyStack')}
                value={(extraction.technologyStack ?? []).join('、') || '-'}
              />
              <InfoItem
                label={t('csInterview.resumeDetail.yearsOfExperience')}
                value={
                  extraction.yearsOfExperience != null
                    ? `${extraction.yearsOfExperience}`
                    : '-'
                }
              />
              <div className="sm:col-span-2">
                <InfoItem
                  label={t('csInterview.resumeDetail.summary')}
                  value={extraction.summary ?? '-'}
                />
              </div>
            </div>
          )}

          {claimedSkills.length > 0 && (
            <div className="mt-6 overflow-x-auto border border-border-button">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border-button bg-bg-card font-mono text-[11px] uppercase tracking-wide text-text-secondary">
                  <tr>
                    <th className="px-4 py-2">
                      {t('csInterview.resumeDetail.claimedSkills')}
                    </th>
                    <th className="px-4 py-2">
                      {t('csInterview.resumeDetail.claimedLevel')}
                    </th>
                    <th className="px-4 py-2">
                      {t('csInterview.resumeDetail.mappedTopics')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {claimedSkills.map((skill) => (
                    <tr
                      key={skill.skill}
                      className="border-b border-border-button last:border-0"
                    >
                      <td className="px-4 py-2 font-medium">{skill.skill}</td>
                      <td className="px-4 py-2">{skill.claimedLevel}</td>
                      <td className="px-4 py-2 text-text-secondary">
                        {(skill.topics ?? []).join(', ') || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {projects.length > 0 && (
            <div className="mt-6 grid gap-4 md:grid-cols-2">
              {projects.map((project) => (
                <div
                  key={project.projectId ?? project.name}
                  className="border border-border-button bg-bg-card p-4"
                >
                  <div className="font-medium">{project.name}</div>
                  {project.role && (
                    <div className="mt-1 text-xs text-text-secondary">
                      {project.role}
                    </div>
                  )}
                  <p className="mt-2 text-sm leading-6 text-text-secondary">
                    {project.summary}
                  </p>
                  {(project.skills ?? []).length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {project.skills.map((skill) => (
                        <span
                          key={skill}
                          className="rounded-full border border-border-button px-2 py-0.5 font-mono text-[10px] text-text-secondary"
                        >
                          {skill}
                        </span>
                      ))}
                    </div>
                  )}
                  {(project.claims ?? []).length > 0 && (
                    <div className="mt-4 space-y-3 border-t border-border-button pt-3">
                      {(project.claims ?? []).map((claim) => (
                        <div key={claim.claimId} className="text-xs leading-5">
                          <div className="font-mono text-[10px] uppercase tracking-wider text-accent-primary">
                            {claim.claimType}
                          </div>
                          <p className="mt-0.5 text-text-primary">
                            {claim.text}
                          </p>
                          <p className="mt-1 text-text-secondary">
                            「{claim.evidenceSpan}」
                          </p>
                          {(claim.riskFlags ?? []).length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {claim.riskFlags.map((flag) => (
                                <span
                                  key={flag}
                                  className="rounded-full border border-state-warning px-2 py-0.5 font-mono text-[10px] text-state-warning"
                                >
                                  {flag}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <SectionTitle icon={UserPlus}>
            {t('csInterview.resumes.createProfile')}
          </SectionTitle>
          <p className="mb-4 text-sm text-text-secondary">
            {t('csInterview.resumeDetail.createProfileHint')}
          </p>
          <div className="max-w-4xl space-y-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <label className="space-y-2 text-sm">
                <span>{t('csInterview.configure.name')}</span>
                <input
                  className={inputClass}
                  value={form.name}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                />
              </label>
              <label className="space-y-2 text-sm">
                <span>{t('csInterview.resumeDetail.targetRole')}</span>
                <select
                  className={selectClass}
                  value={form.targetRole}
                  onChange={(event) =>
                    setForm({ ...form, targetRole: event.target.value })
                  }
                >
                  {DEFAULT_ROLES.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span>{t('csInterview.resumeDetail.targetLevel')}</span>
                <select
                  className={selectClass}
                  value={form.targetLevel}
                  onChange={(event) =>
                    setForm({ ...form, targetLevel: event.target.value })
                  }
                >
                  {DEFAULT_LEVELS.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span>岗位 JD</span>
                <select
                  className={selectClass}
                  value={form.jobId}
                  onChange={(event) =>
                    setForm({ ...form, jobId: event.target.value })
                  }
                >
                  <option value="">请选择已检查的 JD</option>
                  {jobs
                    .filter((job) => job.extraction)
                    .map((job) => (
                      <option key={job.id} value={job.id}>
                        {job.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span>{t('csInterview.resumeDetail.technologyStack')}</span>
                <input
                  className={inputClass}
                  value={form.technologyStack}
                  onChange={(event) =>
                    setForm({ ...form, technologyStack: event.target.value })
                  }
                />
              </label>
              <label className="space-y-2 text-sm">
                <span>{t('csInterview.resumeDetail.mappedTopics')}</span>
                <input
                  className={inputClass}
                  value={form.focusTopics}
                  onChange={(event) =>
                    setForm({ ...form, focusTopics: event.target.value })
                  }
                />
              </label>
            </div>
            <Button
              onClick={handleCreateProfile}
              disabled={!extraction || resume.needsExtraction || !form.jobId}
              size="lg"
            >
              <UserPlus className="size-4" />
              {t('csInterview.resumeDetail.saveProfile')}
            </Button>
            {!extraction && (
              <p className="text-xs text-state-error">
                {t('csInterview.resumeDetail.notExtracted')}
              </p>
            )}
            {extraction && resume.needsExtraction && (
              <p className="text-xs text-state-warning">
                {t('csInterview.resumeDetail.outdatedExtractionHint')}
              </p>
            )}
          </div>
        </section>
      </div>
    </InterviewShell>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-border-button bg-bg-card p-4">
      <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-text-secondary">
        {label}
      </div>
      <div className="mt-1.5 text-sm leading-6">{value}</div>
    </div>
  );
}
