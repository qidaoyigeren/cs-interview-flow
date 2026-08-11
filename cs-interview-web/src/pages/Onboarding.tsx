import { ArrowRight, Check, Eye, FileText, RefreshCcw } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge, Tag } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Spinner, useToast } from '@/components/ui/feedback';
import { Dropzone, validateUpload } from '@/components/upload/Dropzone';
import { useCsMutations, useJobs, useResumes } from '@/hooks/use-cs-query';
import { useCompleteOnboarding } from '@/hooks/use-cs-query';

const RESUME_ACCEPT = ['pdf', 'docx', 'doc', 'txt'];

export function Onboarding() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: resumes = [] } = useResumes();
  const { data: jobs = [] } = useJobs();
  const { uploadResume, createJob, extractJob, seedResume, seedJob, launch } = useCsMutations();
  const completeOnboarding = useCompleteOnboarding();

  const [jdText, setJdText] = useState('');
  const [jdBusy, setJdBusy] = useState(false);

  const parsedResume = resumes.find((r) => r.parseStatus === 'parsed');
  const parsedJob = jobs.find((j) => j.extraction);
  const ready = Boolean(parsedResume && parsedJob);

  const handleResumeFile = (file: File) => {
    const error = validateUpload(file, RESUME_ACCEPT);
    if (error) {
      toast('error', '简历上传失败', error);
      return;
    }
    uploadResume.mutate(
      { file },
      {
        onError: (err) => toast('error', '简历上传失败', err.message),
      },
    );
  };

  const handleJdPaste = async () => {
    if (!jdText.trim()) {
      toast('warning', '请先粘贴 JD 文本', 'JD 文本不能为空，可以从招聘页面复制后粘贴。');
      return;
    }
    setJdBusy(true);
    try {
      const job = await createJob.mutateAsync({
        name: jdText.split('\n')[0]?.replace(/[#*\s]/g, '').slice(0, 30) || '目标岗位 JD',
        sourceText: jdText,
      });
      await extractJob.mutateAsync({ id: job.id });
      toast('success', 'JD 已解析', '已从 JD 文本中提取岗位要求，可在 JD 中心查看或修改。');
    } catch (err) {
      toast('error', 'JD 解析失败', (err as Error).message);
    } finally {
      setJdBusy(false);
    }
  };

  const handleJdFile = async (file: File) => {
    const error = validateUpload(file, ['pdf', 'docx', 'doc', 'txt']);
    if (error) {
      toast('error', 'JD 上传失败', error);
      return;
    }
    setJdBusy(true);
    try {
      const created = await createJob.mutateAsync({
        name: file.name.replace(/\.[^.]+$/, ''),
        sourceText: `（上传文件 ${file.name}，内容为模拟提取的目标岗位 JD）`,
      });
      await extractJob.mutateAsync({ id: created.id });
      toast('success', 'JD 上传并解析成功', '已提取岗位要求，可在 JD 中心修改。');
    } catch (err) {
      toast('error', 'JD 上传失败', (err as Error).message);
    } finally {
      setJdBusy(false);
    }
  };

  const handleStart = () => {
    if (!parsedResume || !parsedJob) return;
    const extraction = parsedResume.extraction;
    launch.mutate(
      {
        resumeId: parsedResume.id,
        jobId: parsedJob.id,
        name: parsedResume.preview?.name ?? '候选人',
        targetRole: extraction?.targetRole ?? parsedJob.name,
        targetLevel: extraction?.targetLevel ?? '初级',
        technologyStack: extraction?.technologyStack ?? [],
        focusTopics: ['go-concurrency', 'mysql', 'redis', 'kafka', 'system-design', 'algorithms'],
        excludedTopics: [],
        initialDifficulty: 'medium',
        preferredCategories: ['baguwen', 'interview_experience', 'leetcode'],
        questionCount: 6,
        maxFollowups: 2,
      },
      {
        onSuccess: (session) => {
          completeOnboarding.mutate(undefined);
          navigate(`/session/${session.id}`);
        },
        onError: (err) => toast('error', '创建面试失败', err.message),
      },
    );
  };

  return (
    <div>
      <PageHeader
        eyebrow="首次设置 · 01"
        title="三步完成第一场模拟面试"
        description="上传简历 → 添加目标 JD → 开始模拟面试。完成后即可进入实时面试，并在结束时获得能力差距报告。"
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Step 1 简历 */}
        <section className="panel flex flex-col p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="flex size-6 items-center justify-center rounded bg-accent-dim font-mono text-xs text-accent">01</span>
              <h2 className="text-sm font-semibold">上传简历</h2>
            </div>
            {parsedResume ? <Badge tone="ok" dot>已就绪</Badge> : <Badge>待完成</Badge>}
          </div>
          {parsedResume ? (
            <div className="flex flex-1 flex-col">
              <div className="flex flex-1 items-start gap-3 rounded border border-line bg-surface p-3.5">
                <FileText className="mt-0.5 size-4 shrink-0 text-accent" />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{parsedResume.fileName}</div>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {(parsedResume.extraction?.technologyStack ?? []).map((skill) => (
                      <Tag key={skill}>{skill}</Tag>
                    ))}
                  </div>
                  <div className="mt-2 font-mono text-[11px] text-ink-tertiary">
                    {parsedResume.chunkCount} 段文本 · 已提取候选人画像
                  </div>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Button size="sm" variant="outline" to={`/resumes/${parsedResume.id}`}>
                  <Eye className="size-3.5" /> 查看详情
                </Button>
                <Button size="sm" variant="ghost" onClick={() => toast('info', '更换简历', '前往简历中心上传新的简历文件。')}>
                  <RefreshCcw className="size-3.5" /> 更换
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 flex-col gap-2.5">
              <Dropzone accept={RESUME_ACCEPT} onFiles={handleResumeFile} busy={uploadResume.isPending} busyLabel="上传中…" />
              <Button variant="ghost" size="sm" onClick={() => seedResume.mutate(undefined, { onError: (e) => toast('error', '填充失败', e.message) })}>
                使用演示简历快速体验
              </Button>
            </div>
          )}
        </section>

        {/* Step 2 JD */}
        <section className="panel flex flex-col p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="flex size-6 items-center justify-center rounded bg-accent-dim font-mono text-xs text-accent">02</span>
              <h2 className="text-sm font-semibold">添加目标 JD</h2>
            </div>
            {parsedJob ? <Badge tone="ok" dot>已就绪</Badge> : <Badge>待完成</Badge>}
          </div>
          {parsedJob ? (
            <div className="flex flex-1 flex-col">
              <div className="flex flex-1 items-start gap-3 rounded border border-line bg-surface p-3.5">
                <FileText className="mt-0.5 size-4 shrink-0 text-accent" />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{parsedJob.name}</div>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {(parsedJob.extraction?.requirements ?? []).slice(0, 4).map((req) => (
                      <Tag key={req.requirementId}>{req.skills[0] ?? req.requirementId}</Tag>
                    ))}
                  </div>
                  <div className="mt-2 font-mono text-[11px] text-ink-tertiary">
                    {parsedJob.extraction?.requirements.length ?? 0} 项岗位要求已提取
                  </div>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Button size="sm" variant="outline" to={`/jobs/${parsedJob.id}`}>
                  <Eye className="size-3.5" /> 查看详情
                </Button>
                <Button size="sm" variant="ghost" onClick={() => toast('info', '更换 JD', '前往 JD 中心上传或粘贴新的 JD。')}>
                  <RefreshCcw className="size-3.5" /> 更换
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 flex-col gap-2.5">
              <textarea
                value={jdText}
                onChange={(event) => setJdText(event.target.value)}
                rows={5}
                placeholder="粘贴目标岗位 JD 文本，或上传 JD 文件…"
                className="w-full resize-y rounded border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-tertiary focus:border-accent focus:outline-none"
              />
              <div className="flex items-center gap-2">
                <Button size="sm" disabled={jdBusy} onClick={handleJdPaste}>
                  {jdBusy ? <Spinner className="size-3.5" /> : null}
                  解析粘贴的 JD
                </Button>
                <Button size="sm" variant="ghost" onClick={() => seedJob.mutate(undefined, { onError: (e) => toast('error', '填充失败', e.message) })}>
                  使用演示 JD
                </Button>
              </div>
              <Dropzone
                accept={RESUME_ACCEPT}
                acceptHint="或上传 JD 文件（PDF / DOCX / DOC / TXT）"
                onFiles={handleJdFile}
                busy={jdBusy}
                busyLabel="解析中…"
              />
            </div>
          )}
        </section>

        {/* Step 3 开始面试 */}
        <section className="panel flex flex-col p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="flex size-6 items-center justify-center rounded bg-accent-dim font-mono text-xs text-accent">03</span>
              <h2 className="text-sm font-semibold">开始模拟面试</h2>
            </div>
            {ready ? <Badge tone="accent" dot>可开始</Badge> : <Badge>待完成</Badge>}
          </div>
          <div className="flex flex-1 flex-col">
            <div className="flex-1 space-y-2 text-sm leading-6 text-ink-secondary">
              <p className="flex items-start gap-2">
                <Check className="mt-1 size-3.5 shrink-0 text-ink-tertiary" />
                基于简历声明与 JD 要求动态出题
              </p>
              <p className="flex items-start gap-2">
                <Check className="mt-1 size-3.5 shrink-0 text-ink-tertiary" />
                每题包含八股、项目、场景或算法题
              </p>
              <p className="flex items-start gap-2">
                <Check className="mt-1 size-3.5 shrink-0 text-ink-tertiary" />
                结束时生成能力差距报告与训练建议
              </p>
            </div>
            <div className="mt-4">
              <Button variant="primary" size="lg" fullWidth disabled={!ready || launch.isPending} onClick={handleStart}>
                {launch.isPending ? <Spinner className="size-4" /> : <ArrowRight className="size-4" />}
                开始模拟面试
              </Button>
              <div className="mt-2.5 text-center">
                <Link
                  to="/"
                  onClick={() => completeOnboarding.mutate(undefined)}
                  className="text-xs text-ink-tertiary underline-offset-4 hover:text-ink-secondary hover:underline"
                >
                  跳过引导，进入面试概览
                </Link>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
