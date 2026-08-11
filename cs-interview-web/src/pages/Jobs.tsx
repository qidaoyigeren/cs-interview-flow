import { BriefcaseBusiness, Plus, UploadCloud } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge, Tag } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Dialog, EmptyState, Spinner, useToast } from '@/components/ui/feedback';
import { Dropzone, validateUpload } from '@/components/upload/Dropzone';
import { useCsMutations, useJobs, useResumes } from '@/hooks/use-cs-query';
import { formatDate } from '@/lib/format';

const RESUME_ACCEPT = ['pdf', 'docx', 'doc', 'txt'];

function skillOverlap(a: string[], b: string[]): boolean {
  return a.some((skillA) => b.some((skillB) => skillA === skillB || skillA.includes(skillB) || skillB.includes(skillA)));
}

export function Jobs() {
  const { toast } = useToast();
  const { data: jobs = [] } = useJobs();
  const { data: resumes = [] } = useResumes();
  const { createJob, extractJob, uploadJob, seedJob } = useCsMutations();

  const [open, setOpen] = useState(false);
  const [jdText, setJdText] = useState('');
  const [busy, setBusy] = useState(false);

  const resumeSkills = resumes.find((r) => r.parseStatus === 'parsed')?.extraction?.technologyStack ?? [];

  const handlePaste = async () => {
    if (!jdText.trim()) {
      toast('warning', '请先粘贴 JD 文本', 'JD 文本不能为空，可以从招聘页面复制后粘贴。');
      return;
    }
    setBusy(true);
    try {
      const job = await createJob.mutateAsync({
        name: jdText.split('\n')[0]?.replace(/[#*\s]/g, '').slice(0, 30) || '目标岗位 JD',
        sourceText: jdText,
      });
      await extractJob.mutateAsync({ id: job.id });
      setOpen(false);
      setJdText('');
      toast('success', 'JD 已解析', '已提取岗位要求，可在详情页修改后保存。');
    } catch (err) {
      toast('error', 'JD 解析失败', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = async (file: File) => {
    const error = validateUpload(file, RESUME_ACCEPT);
    if (error) {
      toast('error', 'JD 上传失败', error);
      return;
    }
    setBusy(true);
    try {
      const job = await uploadJob.mutateAsync({ file });
      await extractJob.mutateAsync({ id: job.id });
      setOpen(false);
      toast('success', 'JD 上传并解析成功', '已提取岗位要求，可在详情页修改后保存。');
    } catch (err) {
      toast('error', 'JD 上传失败', (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const coverageOf = (skills: string[]) => {
    if (resumeSkills.length === 0) return null;
    return skillOverlap(resumeSkills, skills);
  };

  return (
    <div>
      <PageHeader
        eyebrow="JD 中心"
        title="目标岗位 JD"
        description="上传或粘贴目标岗位 JD，自动提取岗位要求与权重，并与简历进行覆盖比对。"
        action={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus className="size-4" /> 添加 JD
          </Button>
        }
      />

      {jobs.length === 0 ? (
        <EmptyState
          icon={BriefcaseBusiness}
          title="还没有目标岗位"
          description="添加一份目标岗位 JD 后，系统会提取岗位要求并与简历比对覆盖情况，指导面试出题方向。"
          action={
            <Button variant="primary" onClick={() => setOpen(true)}>
              添加第一份 JD
            </Button>
          }
        />
      ) : (
        <div className="divide-y divide-line border-y border-line">
          {jobs.map((job) => {
            const mustCount = job.extraction?.requirements.filter((r) => r.category === 'must_have').length ?? 0;
            const niceCount = job.extraction?.requirements.filter((r) => r.category === 'nice_to_have').length ?? 0;
            const covered = (job.extraction?.requirements ?? []).filter((r) => coverageOf(r.skills)).length;
            const total = (job.extraction?.requirements ?? []).length;
            return (
              <Link
                key={job.id}
                to={`/jobs/${job.id}`}
                className="grid grid-cols-1 gap-3 py-4 transition-colors hover:bg-content sm:grid-cols-[1fr_auto] sm:items-center sm:gap-4 sm:px-2"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2.5">
                    <span className="flex size-9 shrink-0 items-center justify-center rounded border border-line bg-surface">
                      <BriefcaseBusiness className="size-4 text-accent" />
                    </span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium group-hover:text-accent">{job.name}</div>
                      <div className="mt-1 font-mono text-xs text-ink-tertiary">
                        {mustCount} 项必备 · {niceCount} 项加分 · 添加于 {formatDate(job.createdAt)}
                      </div>
                    </div>
                  </div>
                  {job.extraction && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5 pl-12">
                      {(job.extraction.requirements ?? []).slice(0, 6).map((req) => (
                        <Tag key={req.requirementId}>{req.skills[0] ?? req.requirementId}</Tag>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-3 sm:justify-end">
                  {total > 0 ? (
                    resumeSkills.length > 0 ? (
                      covered === total ? (
                        <Badge tone="ok" dot>全部覆盖</Badge>
                      ) : covered > 0 ? (
                        <Badge tone="warn" dot>覆盖 {covered}/{total}</Badge>
                      ) : (
                        <Badge tone="err" dot>尚未覆盖</Badge>
                      )
                    ) : (
                      <Badge>待比对</Badge>
                    )
                  ) : (
                    <Badge>待解析</Badge>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="添加目标岗位 JD"
        description="粘贴 JD 文本或上传 JD 文件。解析结果可在 JD 详情页修改。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button variant="primary" disabled={busy || !jdText.trim()} onClick={handlePaste}>
              {busy ? <Spinner className="size-4" /> : <UploadCloud className="size-4" />}
              解析并添加
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <textarea
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
            rows={7}
            placeholder="粘贴目标岗位 JD 全文，包含任职要求与加分项…"
            className="w-full resize-y rounded border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-tertiary focus:border-accent focus:outline-none"
          />
          <Dropzone accept={RESUME_ACCEPT} acceptHint="或上传 JD 文件" onFiles={handleUpload} busy={busy} busyLabel="上传解析中…" />
          <div className="text-right">
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() =>
                seedJob.mutate(undefined, {
                  onSuccess: () => {
                    setOpen(false);
                    toast('success', '已填入演示 JD', '「中级 Go 后端开发工程师」已就绪。');
                  },
                  onError: (err) => toast('error', '填充失败', err.message),
                })
              }
            >
              填入演示 JD
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
