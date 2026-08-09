import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  useInterviewJobs,
  useInterviewMutations,
} from '@/hooks/use-cs-interview-request';
import { Routes } from '@/routes';
import dayjs from 'dayjs';
import { BriefcaseBusiness, FileUp, Plus, Trash2 } from 'lucide-react';
import { FormEvent, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import {
  EmptyState,
  InterviewShell,
  PageHeading,
  SectionTitle,
} from './components';

export default function JobsPage() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const { data: jobs = [], isLoading } = useInterviewJobs();
  const { createJob, uploadJob, deleteJob } = useInterviewMutations();
  const [name, setName] = useState('');
  const [sourceText, setSourceText] = useState('');

  const createFromPaste = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const job = await createJob.mutateAsync({
        name: name.trim(),
        sourceType: 'paste',
        sourceText: sourceText.trim(),
      });
      navigate(`${Routes.CsInterviewJobDetail}/${job.id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  const upload = async (file?: File) => {
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const job = await uploadJob.mutateAsync({ formData });
      navigate(`${Routes.CsInterviewJobDetail}/${job.id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <InterviewShell>
      <PageHeading
        eyebrow="POSITION EVIDENCE"
        title="真实岗位 JD"
        description="上传或粘贴完整 JD。系统只抽取正文中明确出现的要求；无法映射到能力目录的要求仍会保留。"
        action={
          <Button size="lg" variant="outline" onClick={() => fileRef.current?.click()}>
            <FileUp className="size-4" /> 上传 JD
          </Button>
        }
      />
      <input
        ref={fileRef}
        className="hidden"
        type="file"
        accept=".pdf,.doc,.docx,.txt,.md"
        onChange={(event) => {
          upload(event.target.files?.[0]);
          event.target.value = '';
        }}
      />
      <form onSubmit={createFromPaste} className="mb-10 space-y-3 border border-border-button bg-bg-card p-5">
        <SectionTitle icon={Plus}>粘贴岗位描述</SectionTitle>
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="岗位名称"
          required
        />
        <textarea
          value={sourceText}
          onChange={(event) => setSourceText(event.target.value)}
          className="min-h-48 w-full resize-y rounded-md border border-border-button bg-bg-input p-3 text-sm leading-6 outline-none focus:ring-1 focus:ring-accent-primary"
          placeholder="粘贴 JD 正文……"
          required
        />
        <Button type="submit" loading={createJob.isPending}>保存并检查抽取</Button>
      </form>
      <SectionTitle icon={BriefcaseBusiness}>已保存岗位</SectionTitle>
      {isLoading ? (
        <div className="h-32 animate-pulse bg-bg-card" />
      ) : jobs.length === 0 ? (
        <EmptyState title="暂无 JD" description="粘贴或上传一份真实岗位描述后再配置面试。" />
      ) : (
        <div className="divide-y divide-border-button border-y border-border-button">
          {jobs.map((job) => (
            <div key={job.id} className="flex items-center gap-4 py-5 sm:px-4">
              <BriefcaseBusiness className="size-5 text-text-secondary" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{job.name}</div>
                <div className="mt-1 text-xs text-text-secondary">
                  {job.extraction?.requirements.length ?? 0} 条要求 · {dayjs(job.createdAt).format('YYYY-MM-DD')}
                </div>
              </div>
              <Button asLink to={`${Routes.CsInterviewJobDetail}/${job.id}`} size="sm" variant="outline">
                查看与修正
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-state-error"
                onClick={async () => {
                  if (!window.confirm(`删除 ${job.name}？`)) return;
                  try {
                    await deleteJob.mutateAsync({ id: job.id });
                  } catch (error) {
                    toast.error(error instanceof Error ? error.message : String(error));
                  }
                }}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </InterviewShell>
  );
}
