import { Button } from '@/components/ui/button';
import {
  useInterviewJob,
  useInterviewMutations,
} from '@/hooks/use-cs-interview-request';
import { JobExtraction } from '@/interfaces/database/cs-interview';
import { Routes } from '@/routes';
import { AlertTriangle, ArrowLeft, RefreshCw, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router';
import { toast } from 'sonner';
import { InterviewShell, PageHeading, SectionTitle } from './components';

export default function JobDetailPage() {
  const { id = '' } = useParams();
  const { data: job, isLoading } = useInterviewJob(id);
  const { extractJob, patchJob } = useInterviewMutations();
  const [draft, setDraft] = useState('');

  useEffect(() => {
    if (job?.extraction) setDraft(JSON.stringify(job.extraction, null, 2));
  }, [job?.extraction]);

  if (isLoading || !job) {
    return <InterviewShell><div className="h-64 animate-pulse bg-bg-card" /></InterviewShell>;
  }

  const save = async () => {
    try {
      const extraction = JSON.parse(draft) as JobExtraction;
      await patchJob.mutateAsync({ id, extraction });
      toast.success('JD 抽取结果已保存并重新校验');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'JSON 格式无效');
    }
  };

  return (
    <InterviewShell>
      <PageHeading
        eyebrow="AUDITABLE EXTRACTION"
        title={job.name}
        description="证据片段必须逐字来自 JD；topic 只能来自能力目录。保存时服务端会再次确定性校验并重算权重。"
        action={<Button asLink to={Routes.CsInterviewJobs} variant="outline"><ArrowLeft />返回岗位</Button>}
      />
      <div className="grid gap-8 xl:grid-cols-2">
        <section>
          <SectionTitle>JD 原文</SectionTitle>
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap border border-border-button bg-bg-card p-5 text-sm leading-6">
            {job.sourceText}
          </pre>
        </section>
        <section>
          <div className="mb-4 flex items-center justify-between gap-3">
            <SectionTitle>结构化要求</SectionTitle>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                loading={extractJob.isPending}
                onClick={async () => {
                  try {
                    await extractJob.mutateAsync({ id, force: true });
                  } catch (error) {
                    toast.error(error instanceof Error ? error.message : String(error));
                  }
                }}
              >
                <RefreshCw />{job.extraction ? '重新抽取' : '抽取 JD'}
              </Button>
              {job.extraction && <Button size="sm" loading={patchJob.isPending} onClick={save}><Save />保存修正</Button>}
            </div>
          </div>
          {job.extraction ? (
            <>
              {(job.extraction.unmappedRequirementIds?.length ?? 0) > 0 && (
                <div className="mb-4 flex gap-3 border border-state-warning bg-state-warning-5 p-4 text-sm">
                  <AlertTriangle className="size-5 shrink-0 text-state-warning" />
                  {job.extraction.unmappedRequirementIds.length} 条要求无法映射到现有 topic；它们会保留在报告中，但证据不足时不会强行出题。
                </div>
              )}
              <textarea
                aria-label="JD extraction JSON"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                className="min-h-[60vh] w-full resize-y rounded-md border border-border-button bg-bg-input p-4 font-mono text-xs leading-5 outline-none focus:ring-1 focus:ring-accent-primary"
              />
            </>
          ) : (
            <div className="border border-dashed border-border-button p-10 text-center text-sm text-text-secondary">
              尚未抽取。抽取后请在开始面试前检查 evidence_span 与 topic 映射。
            </div>
          )}
        </section>
      </div>
    </InterviewShell>
  );
}
