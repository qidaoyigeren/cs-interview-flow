import { ArrowLeft, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge, Tag } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Field, Input, Select, Textarea } from '@/components/ui/inputs';
import { Loading, Spinner, useToast } from '@/components/ui/feedback';
import { useCsMutations, useJob, useResumes } from '@/hooks/use-cs-query';
import { formatDate } from '@/lib/format';
import type { JDRequirement, JobExtraction } from '@/lib/types';

function skillOverlap(a: string[], b: string[]): boolean {
  return a.some((skillA) => b.some((skillB) => skillA === skillB || skillA.includes(skillB) || skillB.includes(skillA)));
}

const LEVEL_OPTIONS = [
  { value: 'beginner', label: '了解' },
  { value: 'medium', label: '熟悉' },
  { value: 'advanced', label: '精通' },
];

export function JobDetail() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: job, isPending } = useJob(id);
  const { data: resumes = [] } = useResumes();
  const { saveJob, extractJob } = useCsMutations();

  const [draft, setDraft] = useState<JobExtraction | null>(null);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (job?.extraction && !draft) {
      setDraft({ ...job.extraction, requirements: job.extraction.requirements ?? [] });
      setName(job.name);
    }
  }, [job, draft]);

  if (isPending) return <Loading />;
  if (!job) return <Loading label="JD 不存在或已删除…" />;

  if (!job.extraction) {
    return (
      <div>
        <PageHeader eyebrow="JD 详情" title={job.name} description="尚未解析，正在提取岗位要求…" />
        <div className="panel flex items-center justify-center gap-3 p-12">
          <Spinner className="size-5" />
          <Button variant="primary" onClick={() => extractJob.mutate({ id }, { onError: (e) => toast('error', '解析失败', e.message) })}>
            开始解析
          </Button>
        </div>
      </div>
    );
  }

  const resumeSkills = resumes.find((r) => r.parseStatus === 'parsed')?.extraction?.technologyStack ?? [];
  const isCovered = (skills: string[]) => (resumeSkills.length ? skillOverlap(resumeSkills, skills) : false);

  const setRequirement = (index: number, patch: Partial<JDRequirement>) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const next = [...prev.requirements];
      next[index] = { ...next[index]!, ...patch };
      return { ...prev, requirements: next };
    });
  };

  const mustHave = draft?.requirements.filter((r) => r.category === 'must_have') ?? [];
  const niceToHave = draft?.requirements.filter((r) => r.category === 'nice_to_have') ?? [];
  const uncovered = mustHave.filter((r) => !isCovered(r.skills));

  const handleSave = () => {
    if (!draft) return;
    setSaving(true);
    saveJob.mutate(
      { id, extraction: draft },
      {
        onSuccess: (updated) => {
          setSaving(false);
          toast('success', '已保存修改', `「${updated.name}」的岗位要求已更新。`);
        },
        onError: (err) => {
          setSaving(false);
          toast('error', '保存失败', err.message);
        },
      },
    );
  };

  return (
    <div>
      <PageHeader
        eyebrow="JD 详情"
        title={name}
        description="核对岗位要求与权重，保存后作为面试出题与能力验证的依据。"
        action={
          <Button variant="primary" disabled={!draft || saving} onClick={handleSave}>
            {saving ? <Spinner className="size-4" /> : <Save className="size-4" />}
            保存修改
          </Button>
        }
      />

      {!draft ? (
        <Loading />
      ) : (
        <div className="space-y-5">
          {/* 岗位信息 */}
          <section className="panel p-4">
            <div className="micro-label mb-4">岗位信息</div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="sm:col-span-2">
                <Field label="目标岗位" htmlFor="job-name">
                  <Input id="job-name" value={name} onChange={(event) => setName(event.target.value)} />
                </Field>
              </div>
              <Field label="来源">
                <Input value={job.sourceType === 'paste' ? '粘贴文本' : '上传文件'} readOnly />
              </Field>
            </div>
            <div className="mt-4 font-mono text-xs text-ink-tertiary">
              解析于 {formatDate(job.extractedAt)} · 提取版本 {draft.extractionVersion ?? '—'}
            </div>
          </section>

          {/* 覆盖概览 */}
          <section className="panel p-4">
            <div className="micro-label mb-4">简历覆盖情况</div>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div>
                <div className="font-mono text-2xl font-semibold mono-num">{draft.requirements.length}</div>
                <div className="mt-1 text-xs text-ink-tertiary">岗位要求总数</div>
              </div>
              <div>
                <div className="font-mono text-2xl font-semibold mono-num text-ok">
                  {draft.requirements.filter((r) => isCovered(r.skills)).length}
                </div>
                <div className="mt-1 text-xs text-ink-tertiary">简历已覆盖</div>
              </div>
              <div>
                <div className="font-mono text-2xl font-semibold mono-num text-warn">{uncovered.length}</div>
                <div className="mt-1 text-xs text-ink-tertiary">尚未覆盖的必备项</div>
              </div>
              <div>
                <div className="font-mono text-2xl font-semibold mono-num">
                  {resumeSkills.length ? Math.round((draft.requirements.filter((r) => isCovered(r.skills)).length / draft.requirements.length) * 100) : 0}%
                </div>
                <div className="mt-1 text-xs text-ink-tertiary">覆盖比例</div>
              </div>
            </div>
            {uncovered.length > 0 && (
              <div className="mt-4 rounded border border-warn/30 bg-warn-dim/40 p-3">
                <div className="mb-2 flex items-center gap-2 text-xs font-medium text-warn">
                  <span className="size-1.5 rounded-full bg-warn" /> 尚未覆盖的要求（面试重点出题方向）
                </div>
                <ul className="space-y-1.5 text-sm text-ink-secondary">
                  {uncovered.map((req) => (
                    <li key={req.requirementId} className="flex items-start gap-2">
                      <span className="mt-2 size-1 shrink-0 rounded-full bg-ink-tertiary" />
                      {req.text}
                      {req.skills.map((skill) => (
                        <Tag key={skill} className="ml-1">
                          {skill}
                        </Tag>
                      ))}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          {/* 必备技能 */}
          <section className="panel p-4">
            <div className="micro-label mb-4">必备技能（{mustHave.length}）</div>
            <div className="space-y-3">
              {mustHave.map((requirement) => (
                <RequirementCard
                  key={requirement.requirementId}
                  requirement={requirement}
                  index={draft.requirements.indexOf(requirement)}
                  covered={isCovered(requirement.skills)}
                  onChange={setRequirement}
                />
              ))}
            </div>
          </section>

          {/* 加分技能 */}
          <section className="panel p-4">
            <div className="micro-label mb-4">加分技能（{niceToHave.length}）</div>
            {niceToHave.length === 0 ? (
              <div className="rounded border border-dashed border-line p-3 text-xs text-ink-tertiary">
                未识别到加分项。可在下方直接新增。
              </div>
            ) : (
              <div className="space-y-3">
                {niceToHave.map((requirement) => (
                  <RequirementCard
                    key={requirement.requirementId}
                    requirement={requirement}
                    index={draft.requirements.indexOf(requirement)}
                    covered={isCovered(requirement.skills)}
                    onChange={setRequirement}
                  />
                ))}
              </div>
            )}
          </section>

          {/* 业务场景 */}
          <section className="panel p-4">
            <div className="micro-label mb-3">原始 JD 文本</div>
            <Textarea rows={6} value={job.sourceText ?? ''} readOnly className="bg-app" />
          </section>
        </div>
      )}

      <div className="mt-6">
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="size-4" /> 返回 JD 列表
        </Button>
      </div>
    </div>
  );
}

function RequirementCard({
  requirement,
  index,
  covered,
  onChange,
}: {
  requirement: JDRequirement;
  index: number;
  covered: boolean;
  onChange: (index: number, patch: Partial<JDRequirement>) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 rounded border border-line bg-surface p-3 sm:grid-cols-[1fr_110px_120px_1fr_auto] sm:items-end">
      <Field label="岗位要求">
        <Input
          value={requirement.text}
          onChange={(event) => onChange(index, { text: event.target.value })}
        />
      </Field>
      <Field label="权重">
        <Input
          type="number"
          min={0.1}
          max={1}
          step={0.1}
          value={requirement.weight}
          onChange={(event) => onChange(index, { weight: Number(event.target.value) || 0.1 })}
        />
      </Field>
      <Field label="期望级别">
        <Select value={requirement.expectedLevel} onChange={(event) => onChange(index, { expectedLevel: event.target.value })}>
          {LEVEL_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="关联技能（逗号分隔）">
        <Input
          value={requirement.skills.join(', ')}
          onChange={(event) =>
            onChange(index, {
              skills: event.target.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
            })
          }
        />
      </Field>
      <div className="flex items-center gap-2 pb-1">
        {covered ? <Badge tone="ok" dot>已覆盖</Badge> : <Badge tone="err" dot>未覆盖</Badge>}
      </div>
    </div>
  );
}
