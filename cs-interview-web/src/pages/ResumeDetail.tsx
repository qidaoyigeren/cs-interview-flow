import { ArrowLeft, Save, Trash2, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Field, Input, Select, Textarea } from '@/components/ui/inputs';
import { Loading, Spinner, useToast } from '@/components/ui/feedback';
import { useCsMutations, useResume } from '@/hooks/use-cs-query';
import { hrcKey, readHighRiskClaims } from '@/lib/claims';
import { clearStorage, writeStorage } from '@/lib/storage';
import type { ClaimedLevel, HighRiskClaim, ResumeExtraction } from '@/lib/types';

const LEVEL_LABEL: Record<ClaimedLevel, string> = {
  fluent: '精通',
  experienced: '熟练',
  proficient: '扎实',
  familiar: '了解',
  beginner: '入门',
};

const LEVEL_OPTIONS = Object.entries(LEVEL_LABEL).map(([value, label]) => ({ value, label }));

function useHighRiskClaims(resumeId: string, extraction?: ResumeExtraction) {
  const key = hrcKey(resumeId);
  const [claims, setClaims] = useState<HighRiskClaim[]>(() => readHighRiskClaims(resumeId, extraction));

  useEffect(() => {
    if (claims.length > 0) writeStorage(key, claims);
  }, [key, claims]);

  const resetClaims = () => clearStorage(key);

  return { claims, setClaims, resetClaims };
}

export function ResumeDetail() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: resume, isPending } = useResume(id);
  const { saveResume, createProfileFromResume, extractResume } = useCsMutations();

  const [draft, setDraft] = useState<ResumeExtraction | null>(null);
  const { claims, setClaims } = useHighRiskClaims(id, draft ?? undefined);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (resume?.extraction && !draft) {
      setDraft({
        ...resume.extraction,
        technologyStack: resume.extraction.technologyStack ?? [],
        claimedSkills: resume.extraction.claimedSkills ?? [],
        projects: resume.extraction.projects ?? [],
      });
    }
  }, [resume, draft]);

  const set = <K extends keyof ResumeExtraction>(key: K, value: ResumeExtraction[K]) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  if (isPending) return <Loading />;
  if (!resume) return <Loading label="简历不存在或已删除…" />;

  if (resume.parseStatus === 'parsing' || resume.parseStatus === 'pending') {
    return (
      <div>
        <PageHeader eyebrow="简历详情" title={resume.fileName} description="正在解析简历内容…" />
        <div className="panel flex items-center justify-center gap-3 p-12">
          <Spinner className="size-5" />
          <span className="text-sm text-ink-secondary">正在提取技术栈、项目经历与能力声明，请稍候…</span>
        </div>
      </div>
    );
  }

  if (resume.parseStatus === 'failed') {
    return (
      <div>
        <PageHeader eyebrow="简历详情" title={resume.fileName} description="解析失败，请重试或更换文件。" />
        <div className="panel flex flex-col items-center gap-3 p-12 text-center">
          <TriangleAlert className="size-6 text-err" />
          <p className="max-w-md text-sm leading-6 text-ink-secondary">
            无法从文件中提取有效文本。可能是文件损坏、密码保护或格式不支持。请重新导出为 PDF 后上传。
          </p>
          <Button variant="primary" onClick={() => extractResume.mutate({ id }, { onError: (e) => toast('error', '重试失败', e.message) })}>
            重新解析
          </Button>
        </div>
      </div>
    );
  }

  const handleSave = () => {
    if (!draft) return;
    setSaving(true);
    saveResume.mutate(
      { id, extraction: draft },
      {
        onSuccess: (updated) => {
          createProfileFromResume.mutate(
            { id },
            {
              onSuccess: () => {
                setSaving(false);
                toast('success', '已保存为候选人画像', `「${updated.preview?.name ?? '候选人'}」的画像已更新，可作为面试依据。`);
                navigate(`/configure?resume=${id}`);
              },
              onError: (err) => {
                setSaving(false);
                toast('error', '保存失败', err.message);
              },
            },
          );
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
        eyebrow="简历详情"
        title={resume.preview?.name ?? resume.fileName}
        description="核对并修正提取结果。保存后即作为候选人画像，供面试提问与能力验证使用。"
        action={
          <Button variant="primary" disabled={!draft || saving} onClick={handleSave}>
            {saving ? <Spinner className="size-4" /> : <Save className="size-4" />}
            保存为候选人画像
          </Button>
        }
      />

      {!draft ? (
        <Loading />
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
          {/* 基本信息 */}
          <section className="panel p-4 lg:col-span-2">
            <div className="micro-label mb-4">基本信息</div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="姓名" htmlFor="resume-name">
                <Input id="resume-name" value={resume.preview?.name ?? ''} readOnly aria-readonly placeholder="来自文件名" />
              </Field>
              <Field label="目标岗位" htmlFor="resume-role">
                <Input
                  id="resume-role"
                  value={draft.targetRole ?? ''}
                  onChange={(event) => set('targetRole', event.target.value)}
                />
              </Field>
              <Field label="职级" htmlFor="resume-level">
                <Input
                  id="resume-level"
                  value={draft.targetLevel ?? ''}
                  onChange={(event) => set('targetLevel', event.target.value)}
                />
              </Field>
              <Field label="工作年限（年）" htmlFor="resume-years">
                <Input
                  id="resume-years"
                  type="number"
                  min={0}
                  value={draft.yearsOfExperience ?? ''}
                  onChange={(event) => set('yearsOfExperience', Number(event.target.value) || 0)}
                />
              </Field>
            </div>
            <div className="mt-4">
              <Field label="技术栈（逗号分隔）" htmlFor="resume-stack">
                <Input
                  id="resume-stack"
                  value={(draft.technologyStack ?? []).join(', ')}
                  onChange={(event) =>
                    set(
                      'technologyStack',
                      event.target.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
                    )
                  }
                />
              </Field>
            </div>
            <div className="mt-4">
              <Field label="个人简介" htmlFor="resume-summary">
                <Textarea
                  id="resume-summary"
                  rows={4}
                  value={draft.summary ?? ''}
                  onChange={(event) => set('summary', event.target.value)}
                />
              </Field>
            </div>
          </section>

          {/* 高风险声明 */}
          <section className="panel p-4">
            <div className="mb-3 flex items-center gap-2">
              <TriangleAlert className="size-4 text-warn" />
              <h3 className="text-sm font-semibold">可能被追问的高风险声明</h3>
            </div>
            <p className="mb-3 text-xs leading-5 text-ink-tertiary">
              这类声明如果与实际能力不符，最容易在面试中暴露。建议保存前补充可验证的证据或适当下调等级。
            </p>
            <div className="space-y-3">
              {claims.length === 0 ? (
                <div className="rounded border border-dashed border-line p-3 text-xs text-ink-tertiary">
                  暂未识别到高风险声明。自述等级为“扎实/精通”的技能会自动纳入。
                </div>
              ) : (
                claims.map((claim, index) => (
                  <div key={claim.id} className="rounded border border-warn/30 bg-warn-dim/40 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <Input
                        value={claim.claim}
                        aria-label="声明内容"
                        onChange={(event) =>
                          setClaims((prev) => prev.map((c, i) => (i === index ? { ...c, claim: event.target.value } : c)))
                        }
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label="移除声明"
                        onClick={() => setClaims((prev) => prev.filter((_, i) => i !== index))}
                      >
                        <Trash2 className="size-3.5 text-ink-tertiary" />
                      </Button>
                    </div>
                    <Textarea
                      className="mt-2"
                      rows={2}
                      value={claim.reason}
                      aria-label="风险原因"
                      onChange={(event) =>
                        setClaims((prev) => prev.map((c, i) => (i === index ? { ...c, reason: event.target.value } : c)))
                      }
                    />
                  </div>
                ))
              )}
              <Button
                size="sm"
                variant="outline"
                fullWidth
                onClick={() =>
                  setClaims((prev) => [
                    ...prev,
                    {
                      id: `hrc_${Date.now()}`,
                      claim: '新声明（请补充内容）',
                      source: '手动添加',
                      reason: '请描述为什么这条声明容易被追问。',
                      topics: [],
                    },
                  ])
                }
              >
                添加声明
              </Button>
            </div>
          </section>

          {/* 技能声明 */}
          <section className="panel p-4 lg:col-span-3">
            <div className="micro-label mb-4">声明的能力等级与知识主题</div>
            <div className="space-y-3">
              {(draft.claimedSkills ?? []).map((skill, index) => (
                <div key={index} className="grid grid-cols-1 gap-3 rounded border border-line bg-surface p-3 sm:grid-cols-[1.2fr_110px_1.4fr_auto] sm:items-end">
                  <Field label="技能">
                    <Input
                      value={skill.skill}
                      aria-label="技能名称"
                      onChange={(event) =>
                        setDraft((prev) => {
                          if (!prev) return prev;
                          const next = [...(prev.claimedSkills ?? [])];
                          next[index] = { ...next[index]!, skill: event.target.value };
                          return { ...prev, claimedSkills: next };
                        })
                      }
                    />
                  </Field>
                  <Field label="声称等级">
                    <Select
                      value={skill.claimedLevel}
                      aria-label="声称等级"
                      onChange={(event) =>
                        setDraft((prev) => {
                          if (!prev) return prev;
                          const next = [...(prev.claimedSkills ?? [])];
                          next[index] = { ...next[index]!, claimedLevel: event.target.value as ClaimedLevel };
                          return { ...prev, claimedSkills: next };
                        })
                      }
                    >
                      {LEVEL_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="知识主题（逗号分隔）">
                    <Input
                      value={(skill.topics ?? []).join(', ')}
                      aria-label="知识主题"
                      onChange={(event) =>
                        setDraft((prev) => {
                          if (!prev) return prev;
                          const next = [...(prev.claimedSkills ?? [])];
                          next[index] = {
                            ...next[index]!,
                            topics: event.target.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
                          };
                          return { ...prev, claimedSkills: next };
                        })
                      }
                    />
                  </Field>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="删除技能"
                    onClick={() =>
                      setDraft((prev) => (prev ? { ...prev, claimedSkills: (prev.claimedSkills ?? []).filter((_, i) => i !== index) } : prev))
                    }
                  >
                    <Trash2 className="size-3.5 text-ink-tertiary" />
                  </Button>
                </div>
              ))}
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setDraft((prev) =>
                    prev
                      ? {
                          ...prev,
                          claimedSkills: [
                            ...(prev.claimedSkills ?? []),
                            { skill: '新技能', claimedLevel: 'familiar', topics: [] },
                          ],
                        }
                      : prev,
                  )
                }
              >
                添加技能
              </Button>
            </div>
          </section>

          {/* 项目经历 */}
          <section className="panel p-4 lg:col-span-3">
            <div className="micro-label mb-4">项目经历</div>
            <div className="space-y-3">
              {(draft.projects ?? []).map((project, index) => (
                <div key={index} className="grid grid-cols-1 gap-3 rounded border border-line bg-surface p-3 sm:grid-cols-2">
                  <Field label="项目名称">
                    <Input
                      value={project.name}
                      aria-label="项目名称"
                      onChange={(event) =>
                        setDraft((prev) => {
                          if (!prev) return prev;
                          const next = [...(prev.projects ?? [])];
                          next[index] = { ...next[index]!, name: event.target.value };
                          return { ...prev, projects: next };
                        })
                      }
                    />
                  </Field>
                  <Field label="担任角色">
                    <Input
                      value={project.role}
                      aria-label="担任角色"
                      onChange={(event) =>
                        setDraft((prev) => {
                          if (!prev) return prev;
                          const next = [...(prev.projects ?? [])];
                          next[index] = { ...next[index]!, role: event.target.value };
                          return { ...prev, projects: next };
                        })
                      }
                    />
                  </Field>
                  <div className="sm:col-span-2">
                    <Field label="项目简介">
                      <Textarea
                        rows={2}
                        value={project.summary}
                        aria-label="项目简介"
                        onChange={(event) =>
                          setDraft((prev) => {
                            if (!prev) return prev;
                            const next = [...(prev.projects ?? [])];
                            next[index] = { ...next[index]!, summary: event.target.value };
                            return { ...prev, projects: next };
                          })
                        }
                      />
                    </Field>
                  </div>
                  <div className="sm:col-span-2">
                    <Field label="项目使用技术（逗号分隔）">
                      <Input
                        value={(project.skills ?? []).join(', ')}
                        aria-label="项目技术"
                        onChange={(event) =>
                          setDraft((prev) => {
                            if (!prev) return prev;
                            const next = [...(prev.projects ?? [])];
                            next[index] = {
                              ...next[index]!,
                              skills: event.target.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
                            };
                            return { ...prev, projects: next };
                          })
                        }
                      />
                    </Field>
                  </div>
                  <div className="sm:col-span-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setDraft((prev) => (prev ? { ...prev, projects: (prev.projects ?? []).filter((_, i) => i !== index) } : prev))
                      }
                    >
                      <Trash2 className="size-3.5" /> 删除项目
                    </Button>
                  </div>
                </div>
              ))}
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, projects: [...(prev.projects ?? []), { name: '新项目', role: '后端开发', summary: '', skills: [] }] }
                      : prev,
                  )
                }
              >
                添加项目
              </Button>
            </div>
          </section>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="size-4" /> 返回简历列表
        </Button>
        <div className="flex items-center gap-2">
          <Badge>{resume.fileName}</Badge>
          <Badge tone="ok" dot>解析完成</Badge>
        </div>
      </div>
    </div>
  );
}
