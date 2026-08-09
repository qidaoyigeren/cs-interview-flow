import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Routes } from '@/routes';
import { useInterviewMutations, useInterviewResumes } from '@/hooks/use-cs-interview-request';
import { ResumeParseStatus } from '@/interfaces/database/cs-interview';
import dayjs from 'dayjs';
import { FileText, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import {
  EmptyState,
  InterviewShell,
  PageHeading,
  SectionTitle,
} from './components';

export const ResumeStatusPill = ({ status }: { status: ResumeParseStatus }) => {
  const { t } = useTranslation();
  const active = status === 'parsing';
  const ok = status === 'parsed';
  const failed = status === 'failed';
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wide',
        ok && 'border-state-success bg-state-success-5 text-state-success',
        active && 'border-accent-primary bg-accent-primary-5 text-text-primary',
        failed && 'border-state-error bg-state-error-5 text-state-error',
        !ok && !active && !failed && 'border-border-button text-text-secondary',
      )}
    >
      <span
        className={cn(
          'size-1.5 rounded-full bg-text-secondary',
          ok && 'bg-state-success',
          active && 'bg-accent-primary',
          failed && 'bg-state-error',
        )}
      />
      {t(`csInterview.resumes.status.${status}`, { defaultValue: status })}
    </span>
  );
};

export default function ResumesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { data: resumes = [], isLoading } = useInterviewResumes();
  const { uploadResume, deleteResume } = useInterviewMutations();

  const handleFileChosen = async (file: File | null) => {
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const resume = await uploadResume.mutateAsync({ formData });
      navigate(`${Routes.CsInterviewResumeDetail}/${resume.id}`);
    } catch {
      toast.error(t('csInterview.resumes.uploadError'));
    }
  };

  const handleDelete = async (id: string, fileName: string) => {
    if (!window.confirm(t('csInterview.resumes.deleteConfirm'))) return;
    try {
      await deleteResume.mutateAsync({ id });
      toast.success(fileName);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <InterviewShell>
      <PageHeading
        eyebrow={t('csInterview.resumes.eyebrow')}
        title={t('csInterview.resumes.title')}
        description={t('csInterview.resumes.description')}
        action={
          <Button onClick={() => fileInputRef.current?.click()} size="lg">
            <Plus className="size-4" />
            {t('csInterview.resumes.upload')}
          </Button>
        }
      />
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx,.doc,.txt"
        className="hidden"
        onChange={(event) => {
          handleFileChosen(event.target.files?.[0] ?? null);
          event.target.value = '';
        }}
      />
      <p className="mb-6 text-xs text-text-secondary">
        {t('csInterview.resumes.uploadHint')}
      </p>
      <SectionTitle icon={FileText}>{t('csInterview.resumes.title')}</SectionTitle>
      {isLoading ? (
        <div className="h-32 animate-pulse bg-bg-card" />
      ) : resumes.length === 0 ? (
        <EmptyState
          title={t('csInterview.resumes.emptyTitle')}
          description={t('csInterview.resumes.emptyDescription')}
          action={
            <Button
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
            >
              <Plus className="size-4" />
              {t('csInterview.resumes.upload')}
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {resumes.map((resume) => (
            <div
              key={resume.id}
              className="flex flex-col gap-4 border border-border-button bg-bg-card p-5"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <FileText className="size-5 shrink-0 text-text-secondary" />
                  <div className="min-w-0">
                    <div className="truncate font-medium">{resume.fileName}</div>
                    <div className="mt-1 font-mono text-[11px] uppercase text-text-secondary">
                      .{resume.fileType}
                    </div>
                  </div>
                </div>
                <ResumeStatusPill status={resume.parseStatus} />
              </div>
              <div className="flex items-center gap-4 text-xs text-text-secondary">
                <span>
                  {resume.chunkCount} {t('csInterview.resumeDetail.chunks')}
                </span>
                <span>{dayjs(resume.createdAt).format('YYYY-MM-DD')}</span>
              </div>
              <div className="mt-auto flex flex-wrap gap-2">
                <Button asLink to={`${Routes.CsInterviewResumeDetail}/${resume.id}`} variant="outline" size="sm">
                  {t('csInterview.resumes.view')}
                </Button>
                {resume.parseStatus === 'parsed' && !resume.extraction && (
                  <Button asLink to={`${Routes.CsInterviewResumeDetail}/${resume.id}`} variant="outline" size="sm">
                    <RefreshCw className="size-3" />
                    {t('csInterview.resumes.extract')}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto text-state-error"
                  onClick={() => handleDelete(resume.id, resume.fileName)}
                >
                  <Trash2 className="size-3" />
                  {t('csInterview.resumes.delete')}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </InterviewShell>
  );
}
