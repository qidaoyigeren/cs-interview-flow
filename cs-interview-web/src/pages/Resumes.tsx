import { FileText, RotateCw, Trash2, UploadCloud } from 'lucide-react';
import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog, EmptyState, Spinner, useToast } from '@/components/ui/feedback';
import { Dropzone, validateUpload } from '@/components/upload/Dropzone';
import { useCsMutations, useResumes } from '@/hooks/use-cs-query';
import { formatDate } from '@/lib/format';
import type { InterviewResume } from '@/lib/types';

const RESUME_ACCEPT = ['pdf', 'docx', 'doc', 'txt'];

function ResumeStatus({ status }: { status: InterviewResume['parseStatus'] }) {
  if (status === 'parsed') return <Badge tone="ok" dot>已提取</Badge>;
  if (status === 'parsing')
    return (
      <span className="inline-flex items-center gap-1.5">
        <Spinner className="size-3.5 text-accent" />
        <Badge tone="accent" dot>解析中</Badge>
      </span>
    );
  if (status === 'pending')
    return (
      <span className="inline-flex items-center gap-1.5">
        <Spinner className="size-3.5 text-accent" />
        <Badge tone="accent" dot>上传中</Badge>
      </span>
    );
  return <Badge tone="err" dot>解析失败</Badge>;
}

export function Resumes() {
  const { toast } = useToast();
  const { data: resumes = [] } = useResumes();
  const { uploadResume, extractResume, deleteResume } = useCsMutations();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [deleteTarget, setDeleteTarget] = useState<InterviewResume | null>(null);

  const handleFile = (file: File) => {
    const error = validateUpload(file, RESUME_ACCEPT);
    if (error) {
      toast('error', '上传失败', error);
      return;
    }
    uploadResume.mutate(
      { file },
      {
        onError: (err) => toast('error', '上传失败', err.message),
      },
    );
  };

  return (
    <div>
      <PageHeader
        eyebrow="简历中心"
        title="候选人简历"
        description="上传简历后自动提取候选人画像：技术栈、项目经历与声明的能力等级，作为面试追问的依据。"
        action={
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept={RESUME_ACCEPT.map((ext) => `.${ext}`).join(',')}
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) handleFile(file);
                event.target.value = '';
              }}
            />
            <Button variant="primary" onClick={() => fileInputRef.current?.click()}>
              <UploadCloud className="size-4" /> 上传简历
            </Button>
          </>
        }
      />

      <div className="mb-6">
        <Dropzone
          accept={RESUME_ACCEPT}
          acceptHint="支持 PDF / DOCX / DOC / TXT，单个文件不超过 20MB"
          onFiles={handleFile}
          busy={uploadResume.isPending}
          busyLabel="上传中，请稍候…"
        />
      </div>

      {resumes.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="还没有简历"
          description="上传一份简历后，系统会自动提取技术栈、项目经历和声明的能力等级，作为面试提问与验证的依据。"
          action={
            <Button variant="primary" onClick={() => fileInputRef.current?.click()}>
              上传第一份简历
            </Button>
          }
        />
      ) : (
        <div className="divide-y divide-line border-y border-line">
          {resumes.map((resume) => {
            const parsed = resume.parseStatus === 'parsed';
            const failed = resume.parseStatus === 'failed';
            return (
              <div key={resume.id} className="grid grid-cols-1 gap-3 py-4 sm:grid-cols-[1fr_auto_auto] sm:items-center sm:gap-4">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded border border-line bg-surface">
                    <FileText className="size-4 text-accent" />
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{resume.fileName}</div>
                    <div className="mt-1 font-mono text-xs text-ink-tertiary">
                      {parsed
                        ? `${resume.chunkCount} 段文本 · ${resume.extraction?.technologyStack?.join(' / ') ?? '已提取'} · 提取于 ${formatDate(resume.extractedAt)}`
                        : `上传于 ${formatDate(resume.createdAt)}`}
                    </div>
                    {resume.parseStatus === 'parsed' && resume.preview && (
                      <div className="mt-1.5 truncate font-mono text-[11px] text-ink-secondary">
                        {resume.preview.name} · {resume.preview.projectNames?.join(' · ')}
                      </div>
                    )}
                    {failed && (
                      <div className="mt-1.5 text-xs text-err">
                        解析失败：文件内容无法识别。请确认文件未损坏，或尝试更换格式后重新上传。
                      </div>
                    )}
                  </div>
                </div>
                <ResumeStatus status={resume.parseStatus} />
                <div className="flex items-center gap-1">
                  {failed && (
                    <Button size="sm" variant="ghost" onClick={() => extractResume.mutate({ id: resume.id }, { onError: (e) => toast('error', '重试失败', e.message) })}>
                      <RotateCw className="size-3.5" /> 重试
                    </Button>
                  )}
                  {parsed && (
                    <Button size="sm" variant="outline" to={`/resumes/${resume.id}`}>
                      查看详情
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`删除 ${resume.fileName}`}
                    onClick={() => setDeleteTarget(resume)}
                  >
                    <Trash2 className="size-3.5 text-ink-tertiary" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) {
            deleteResume.mutate(
              { id: deleteTarget.id },
              {
                onSuccess: () => toast('success', '已删除简历'),
                onError: (err) => toast('error', '删除失败', err.message),
              },
            );
          }
        }}
        title="删除这份简历？"
        description={`将删除「${deleteTarget?.fileName ?? ''}」及其提取结果。此操作不可撤销。`}
        confirmText="删除"
        danger
      />

      <div className="mt-4 text-xs leading-5 text-ink-tertiary">
        <Link to="/jobs" className="text-ink-secondary underline-offset-4 hover:underline">
          已提取简历？
        </Link>
        {' '}下一步建议前往 JD 中心添加目标岗位，或在“新建面试”中选择岗位开始模拟面试。
      </div>
    </div>
  );
}
