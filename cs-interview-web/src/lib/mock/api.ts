/**
 * Mock API 层：镜像 api/apps/restful_apis/cs_interview_api.py 的方法语义与对象形状，
 * 但数据持久化到 localStorage，并模拟 500–900ms 网络延迟。
 * 后续接入真实后端时，仅需替换本文件实现。
 */
import type {
  CandidateAnswer,
  CodeSubmission,
  InterviewJob,
  InterviewProfile,
  InterviewResume,
  InterviewRound,
  InterviewSession,
  JobExtraction,
  ResumeExtraction,
} from '@/lib/types';
import { newId, persist, readDb, updateDb, upsert } from './db';
import {
  demoJob,
  demoJobRequirements,
  demoResume,
  demoResumeExtraction,
  questionBank,
  type BankQuestion,
} from './demo';
import { buildReport } from './report';

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const randomDelay = () => delay(500 + Math.random() * 400);
const nowIso = () => new Date().toISOString();

export type ProgressStage =
  | 'received'
  | 'evaluating'
  | 'feedback'
  | 'deciding'
  | 'followup'
  | 'next'
  | 'completed'
  | 'error';

export type AnswerOutcome =
  | { type: 'followup'; followupQuestion: string; reason: string }
  | { type: 'next'; sequence: number }
  | { type: 'completed' };

export interface SubmitResult {
  session: InterviewSession;
  outcome: AnswerOutcome;
}

/* ---------------- 工具 ---------------- */

function activeRound(session: InterviewSession): InterviewRound | undefined {
  if (!session.rounds || session.rounds.length === 0) return undefined;
  return session.rounds.find((r) => r.status !== 'evaluated') ?? session.rounds[session.rounds.length - 1];
}

function makeRoundFromBank(
  q: BankQuestion,
  session: InterviewSession,
  sequence: number,
): InterviewRound {
  return {
    id: newId('round'),
    sessionId: session.id,
    sequence,
    status: 'awaiting_answer',
    questionId: q.id,
    category: q.category,
    topic: q.topic,
    questionType: q.questionType,
    difficulty: q.difficulty,
    questionText: q.questionText,
    candidateAnswers: [],
    followupQuestions: [],
    followupCount: 0,
    resumeProbe: q.resumeProbe,
    targetRequirementId: q.targetRequirementId,
    targetTopic: q.topic,
    questionReason: q.reason,
    evidenceSources: [
      {
        evidenceId: `ev_${q.id}`,
        datasetId: q.evidenceSource.datasetId,
        documentName: q.evidenceSource.documentName,
        source: q.evidenceSource.source,
        sourceDate: q.evidenceSource.sourceDate,
        qualityScore: q.evidenceSource.qualityScore,
      },
    ],
  };
}

/** 根据画像与已答题选择下一题：优先未覆盖的 JD 要求；保证算法题至少出现一次。 */
function pickNextQuestion(session: InterviewSession, profile?: InterviewProfile): BankQuestion | null {
  const asked = new Set(session.rounds?.map((r) => r.questionId) ?? []);
  const answeredReq = new Set(
    session.rounds?.map((r) => r.targetRequirementId).filter(Boolean) as string[] ?? [],
  );
  const excluded = new Set(profile?.excludedTopics ?? []);
  const focus = profile?.focusTopics ?? [];

  let pool = questionBank.filter((q) => !asked.has(q.id) && !excluded.has(q.topic));
  if (pool.length === 0) return null;

  // 算法题安排在中间/后半程，避免首题直接是算法题
  const hasCoding = session.rounds?.some((r) => r.questionType === 'coding');
  const playedCount = session.rounds?.length ?? 0;
  const isLastRound = playedCount >= (profile?.questionCount ?? 6) - 1;
  if (!hasCoding && (playedCount >= 1 || isLastRound)) {
    const coding = pool.find((q) => q.questionType === 'coding');
    if (coding) return coding;
  }

  const priority = pool.filter((q) => {
    if (!q.targetRequirementId) return false;
    if (answeredReq.has(q.targetRequirementId)) return false;
    return focus.length === 0 || focus.includes(q.topic);
  });
  return (priority.length ? priority : pool)[0] ?? null;
}

/** 文本回答评分：基于参考要点关键词命中 + 回答完整度（0-5）。 */
function evaluateAnswer(round: InterviewRound, answer: string) {
  const bank = questionBank.find((q) => q.id === round.questionId);
  const reference = bank?.referenceAnswer ?? '';
  const terms = reference
    .replace(/[，。；：、？（）\s]/g, '|')
    .split('|')
    .map((s) => s.trim())
    .filter((s) => s.length >= 2);
  const hit = terms.filter((term) => answer.includes(term)).length;
  const lengthFactor = Math.min(1.5, answer.length / 60);
  let score = 2 + hit * 0.45 + lengthFactor;
  score = Math.max(0.8, Math.min(5, Math.round(score * 10) / 10));
  const verdict = score >= 3.7 ? 'pass' : score >= 3.1 ? 'partial' : 'fail';
  return { score, verdict, hit, reference };
}

/* ---------------- 简历 ---------------- */

async function simulateResumeParsing(id: string): Promise<void> {
  await delay(700);
  updateDb((db) => {
    const resume = db.resumes.find((r) => r.id === id);
    if (!resume) return;
    resume.parseStatus = 'parsing';
    resume.updatedAt = nowIso();
  });
  await delay(900);
  updateDb((db) => {
    const resume = db.resumes.find((r) => r.id === id);
    if (!resume) return;
    resume.parseStatus = 'parsed';
    resume.extraction = demoResumeExtraction;
    resume.extractedAt = nowIso();
    resume.updatedAt = nowIso();
    resume.preview = {
      name: demoResumeExtraction.targetRole ?? '候选人',
      skills: demoResumeExtraction.technologyStack ?? [],
      projectNames: demoResumeExtraction.projects?.map((p) => p.name) ?? [],
    };
  });
}

export const mockApi = {
  /* ---- 简历 ---- */
  async listResumes(): Promise<InterviewResume[]> {
    await randomDelay();
    return readDb().resumes;
  },
  async getResume(id: string): Promise<InterviewResume> {
    await randomDelay();
    const resume = readDb().resumes.find((r) => r.id === id);
    if (!resume) throw new Error(`未找到简历 ${id}`);
    return resume;
  },
  async uploadResume(fileName: string, fileType: string): Promise<InterviewResume> {
    await delay(400);
    const id = newId('res');
    const resume: InterviewResume = {
      id,
      fileName,
      fileType,
      parseStatus: 'pending',
      chunkCount: 0,
      createdAt: nowIso(),
      updatedAt: nowIso(),
    };
    updateDb((db) => {
      db.resumes = upsert(db.resumes, resume);
    });
    void simulateResumeParsing(id);
    return resume;
  },
  async extractResume(id: string): Promise<InterviewResume> {
    await randomDelay();
    void simulateResumeParsing(id);
    const db = readDb();
    return db.resumes.find((r) => r.id === id) ?? (await this.getResume(id));
  },
  async patchResume(id: string, extraction: ResumeExtraction): Promise<InterviewResume> {
    await randomDelay();
    updateDb((db) => {
      const resume = db.resumes.find((r) => r.id === id);
      if (resume) {
        resume.extraction = extraction;
        resume.parseStatus = 'parsed';
        resume.updatedAt = nowIso();
      }
    });
    return readDb().resumes.find((r) => r.id === id) as InterviewResume;
  },
  async deleteResume(id: string): Promise<void> {
    await randomDelay();
    updateDb((db) => {
      db.resumes = db.resumes.filter((r) => r.id !== id);
      db.profiles = db.profiles.filter((p) => p.resumeId !== id);
    });
  },
  async createProfileFromResume(id: string): Promise<InterviewProfile> {
    await randomDelay();
    const resume = readDb().resumes.find((r) => r.id === id);
    const extraction = resume?.extraction;
    const existing = readDb().profiles.find((p) => p.resumeId === id);
    const base: Pick<
      InterviewProfile,
      | 'name'
      | 'targetRole'
      | 'targetLevel'
      | 'technologyStack'
      | 'focusTopics'
      | 'excludedTopics'
      | 'initialDifficulty'
      | 'preferredCategories'
      | 'questionCount'
      | 'maxFollowups'
      | 'resumeId'
    > = {
      name: resume?.preview?.name ?? '候选人',
      targetRole: extraction?.targetRole ?? '软件开发工程师',
      targetLevel: extraction?.targetLevel ?? '初级',
      technologyStack: extraction?.technologyStack ?? [],
      focusTopics: ['go-concurrency', 'mysql', 'redis', 'system-design'],
      excludedTopics: [],
      initialDifficulty: 'medium',
      preferredCategories: ['baguwen', 'interview_experience', 'leetcode'],
      questionCount: 6,
      maxFollowups: 2,
      resumeId: id,
    };
    const profile: InterviewProfile = existing
      ? { ...existing, ...base, updatedAt: nowIso() }
      : { ...base, id: newId('prof'), createdAt: nowIso(), updatedAt: nowIso() };
    updateDb((db) => {
      db.profiles = upsert(db.profiles, profile);
    });
    return profile;
  },

  /* ---- JD ---- */
  async listJobs(): Promise<InterviewJob[]> {
    await randomDelay();
    return readDb().jobs;
  },
  async getJob(id: string): Promise<InterviewJob> {
    await randomDelay();
    const job = readDb().jobs.find((j) => j.id === id);
    if (!job) throw new Error(`未找到 JD ${id}`);
    return job;
  },
  async createJob(name: string, sourceText: string): Promise<InterviewJob> {
    await delay(350);
    const job: InterviewJob = {
      id: newId('job'),
      name: name || '目标岗位 JD',
      sourceType: 'paste',
      sourceText,
      createdAt: nowIso(),
      updatedAt: nowIso(),
    };
    updateDb((db) => {
      db.jobs = upsert(db.jobs, job);
    });
    return job;
  },
  async uploadJob(fileName: string): Promise<InterviewJob> {
    await delay(350);
    const job: InterviewJob = {
      id: newId('job'),
      name: fileName.replace(/\.[^.]+$/, '') || '目标岗位 JD',
      sourceType: 'file',
      sourceText: '（上传文件内容模拟提取）',
      createdAt: nowIso(),
      updatedAt: nowIso(),
    };
    updateDb((db) => {
      db.jobs = upsert(db.jobs, job);
    });
    return job;
  },
  async extractJob(id: string): Promise<InterviewJob> {
    await randomDelay();
    const db = readDb();
    const job = db.jobs.find((j) => j.id === id);
    if (!job) throw new Error(`未找到 JD ${id}`);
    const extraction = job.sourceText
      ? deriveJobExtraction(job.sourceText)
      : { requirements: demoJobRequirements, unmappedRequirementIds: [], extractionVersion: '1.0' };
    updateDb((dbState) => {
      const target = dbState.jobs.find((j) => j.id === id);
      if (target) {
        target.extraction = extraction;
        target.extractionVersion = extraction.extractionVersion;
        target.extractedAt = nowIso();
        target.updatedAt = nowIso();
      }
    });
    return readDb().jobs.find((j) => j.id === id) as InterviewJob;
  },
  async patchJob(id: string, extraction: InterviewJob['extraction']): Promise<InterviewJob> {
    await randomDelay();
    updateDb((db) => {
      const job = db.jobs.find((j) => j.id === id);
      if (job) {
        job.extraction = extraction;
        job.extractedAt = nowIso();
        job.updatedAt = nowIso();
      }
    });
    return readDb().jobs.find((j) => j.id === id) as InterviewJob;
  },
  async deleteJob(id: string): Promise<void> {
    await randomDelay();
    updateDb((db) => {
      db.jobs = db.jobs.filter((j) => j.id !== id);
    });
  },

  /* ---- 画像 ---- */
  async listProfiles(): Promise<InterviewProfile[]> {
    await randomDelay();
    return readDb().profiles;
  },
  async createProfile(payload: Omit<InterviewProfile, 'id' | 'createdAt' | 'updatedAt'>): Promise<InterviewProfile> {
    await randomDelay();
    const profile: InterviewProfile = {
      ...payload,
      id: newId('prof'),
      createdAt: nowIso(),
      updatedAt: nowIso(),
    };
    updateDb((db) => {
      db.profiles = upsert(db.profiles, profile);
    });
    return profile;
  },

  /** 幂等确保画像存在：按 resumeId+jobId 复用或更新，供新建面试与首次引导共用。 */
  async ensureProfile(payload: {
    resumeId?: string;
    jobId?: string;
    name: string;
    targetRole: string;
    targetLevel: string;
    technologyStack: string[];
    focusTopics: string[];
    excludedTopics: string[];
    initialDifficulty: InterviewProfile['initialDifficulty'];
    preferredCategories: InterviewProfile['preferredCategories'];
    questionCount: number;
    maxFollowups: number;
  }): Promise<InterviewProfile> {
    await randomDelay();
    const db = readDb();
    const existing = db.profiles.find(
      (p) => p.resumeId === payload.resumeId && p.jobId === payload.jobId,
    );
    const profile: InterviewProfile = existing
      ? {
          ...existing,
          ...payload,
          updatedAt: nowIso(),
        }
      : {
          ...payload,
          id: newId('prof'),
          createdAt: nowIso(),
          updatedAt: nowIso(),
        };
    updateDb((dbState) => {
      dbState.profiles = upsert(dbState.profiles, profile);
    });
    return profile;
  },

  /** 一键启动面试：幂等确保画像后创建会话并生成第一题。 */
  async launchInterview(payload: {
    resumeId?: string;
    jobId?: string;
    name: string;
    targetRole: string;
    targetLevel: string;
    technologyStack: string[];
    focusTopics: string[];
    excludedTopics: string[];
    initialDifficulty: InterviewProfile['initialDifficulty'];
    preferredCategories: InterviewProfile['preferredCategories'];
    questionCount: number;
    maxFollowups: number;
    enableCodeExecution?: boolean;
  }): Promise<InterviewSession> {
    const profile = await this.ensureProfile(payload);
    return this.createSession({
      profileId: profile.id,
      enableCodeExecution: payload.enableCodeExecution,
    });
  },

  /** 演示数据快速填充：简历不存在时补入演示简历。 */
  async seedDemoResume(): Promise<InterviewResume> {
    await delay(300);
    updateDb((db) => {
      if (!db.resumes.some((r) => r.id === demoResume.id)) {
        db.resumes = upsert(db.resumes, demoResume);
      }
    });
    return demoResume;
  },

  /** 演示数据快速填充：JD 不存在时补入演示 JD。 */
  async seedDemoJob(): Promise<InterviewJob> {
    await delay(300);
    updateDb((db) => {
      if (!db.jobs.some((j) => j.id === demoJob.id)) {
        db.jobs = upsert(db.jobs, demoJob);
      }
    });
    return demoJob;
  },

  /* ---- 知识源 ---- */
  async listDatasets() {
    await randomDelay();
    return readDb().datasets;
  },
  async getKnowledgeConfig() {
    await randomDelay();
    return readDb().knowledgeConfig;
  },
  async saveKnowledgeConfig(payload: { enabled: boolean }) {
    await randomDelay();
    updateDb((db) => {
      if (db.knowledgeConfig) {
        db.knowledgeConfig.enabled = payload.enabled;
        db.knowledgeConfig.updatedAt = nowIso();
      }
    });
    return readDb().knowledgeConfig;
  },

  /* ---- 会话 ---- */
  async listSessions(): Promise<InterviewSession[]> {
    await randomDelay();
    return readDb().sessions;
  },
  async getSession(id: string): Promise<InterviewSession> {
    await randomDelay();
    const session = readDb().sessions.find((s) => s.id === id);
    if (!session) throw new Error(`未找到面试 ${id}`);
    return session;
  },
  async createSession(payload: { profileId: string; enableCodeExecution?: boolean }): Promise<InterviewSession> {
    await delay(500);
    const db = readDb();
    const profile = db.profiles.find((p) => p.id === payload.profileId);
    const job = profile?.jobId ? db.jobs.find((j) => j.id === profile.jobId) : undefined;
    const session = {
      id: newId('ses'),
      profileId: payload.profileId,
      knowledgeConfigId: db.knowledgeConfig?.id ?? '',
      status: 'preparing_question',
      currentDifficulty: profile?.initialDifficulty ?? 'medium',
      maxQuestions: profile?.questionCount ?? 6,
      maxFollowups: profile?.maxFollowups ?? 2,
      completedQuestionCount: 0,
      currentRoundSequence: 0,
      stateVersion: 1,
      promptVersion: '1.0',
      plannerVersion: '1.0',
      job: job
        ? { id: job.id, name: job.name, unmappedRequirementIds: job.extraction?.unmappedRequirementIds ?? [] }
        : undefined,
      startedAt: nowIso(),
      createdAt: nowIso(),
      updatedAt: nowIso(),
      rounds: [],
      enableCodeExecution: payload.enableCodeExecution ?? true,
    } as InterviewSession;
    updateDb((dbState) => {
      dbState.sessions = upsert(dbState.sessions, session);
    });
    // 生成第一题
    await delay(400);
    updateDb((dbState) => {
      const target = dbState.sessions.find((s) => s.id === session.id)!;
      const next = pickNextQuestion(target, profile);
      if (next) {
        target.rounds = [makeRoundFromBank(next, target, 1)];
        target.currentRoundSequence = 1;
        target.status = 'awaiting_answer';
        target.updatedAt = nowIso();
      } else {
        target.status = 'completed';
        target.completedAt = nowIso();
      }
    });
    return readDb().sessions.find((s) => s.id === session.id) as InterviewSession;
  },

  async submitAnswer(
    sessionId: string,
    answer: string,
    onProgress?: (stage: ProgressStage) => void,
  ): Promise<SubmitResult> {
    const db = readDb();
    const session = db.sessions.find((s) => s.id === sessionId);
    if (!session) throw new Error(`未找到面试 ${sessionId}`);
    const round = activeRound(session);
    if (!round || round.questionType === 'coding') {
      throw new Error('当前轮次不是文本题，请使用代码提交。');
    }

    onProgress?.('received');
    await delay(380);
    const kind: CandidateAnswer['kind'] = round.candidateAnswers.length === 0 ? 'initial' : 'followup';
    round.candidateAnswers.push({ kind, answer, submittedAt: nowIso() });
    session.status = 'evaluating';
    round.status = 'evaluating';
    persist(db);
    onProgress?.('evaluating');
    await delay(620);

    const { score, verdict } = evaluateAnswer(round, answer);
    onProgress?.('feedback');
    await delay(420);

    const canFollowup = round.followupCount < session.maxFollowups;
    const wantFollowup = canFollowup && score < 3.6 && kind === 'initial';
    if (wantFollowup) {
      onProgress?.('deciding');
      await delay(320);
      const followupQuestion = buildFollowup(round);
      round.followupQuestions.push({
        sequence: round.followupCount + 1,
        question: followupQuestion,
        selectedAction: 'followup',
        reason: score < 3.1 ? '初始回答覆盖不足，需继续验证。' : '需要进一步确认细节，验证是否只是名词熟悉。',
        askedAt: nowIso(),
      });
      round.followupCount += 1;
      round.status = 'awaiting_answer';
      session.status = 'awaiting_answer';
      session.updatedAt = nowIso();
      persist(db);
      onProgress?.('followup');
      return { session, outcome: { type: 'followup', followupQuestion, reason: '需要进一步确认的内容' } };
    }

    // 结算本轮
    round.initialScore = round.candidateAnswers[0]?.evaluation?.score ?? score;
    round.score = score;
    round.verdict = verdict;
    round.evaluationSummary = buildRoundSummary(round);
    round.feedback = verdict === 'pass' ? '该能力已获得充分证据。' : verdict === 'partial' ? '部分理解正确，建议补强细节。' : '回答不足，建议系统复习后重测。';
    round.weakPoint = score < 3.1 ? '关键概念缺失' : '细节深度不足';
    round.status = 'evaluated';
    session.completedQuestionCount += 1;

    const profile = readDb().profiles.find((p) => p.id === session.profileId);
    const next = session.completedQuestionCount < session.maxQuestions ? pickNextQuestion(session, profile) : null;
    if (next) {
      onProgress?.('deciding');
      await delay(320);
      session.rounds = [...(session.rounds ?? []), makeRoundFromBank(next, session, (session.rounds?.length ?? 0) + 1)];
      session.currentRoundSequence = session.rounds.length;
      session.currentDifficulty = next.difficulty;
      session.status = 'awaiting_answer';
      session.updatedAt = nowIso();
      persist(db);
      onProgress?.('next');
      return { session, outcome: { type: 'next', sequence: session.rounds.length } };
    }

    session.status = 'completed';
    session.currentRoundSequence = session.rounds?.length ?? session.completedQuestionCount;
    session.completedAt = nowIso();
    session.report = buildReport(session);
    session.updatedAt = nowIso();
    persist(db);
    onProgress?.('completed');
    return { session, outcome: { type: 'completed' } };
  },

  async runCode(
    sessionId: string,
    roundId: string,
    language: string,
    sourceCode: string,
  ): Promise<CodeSubmission> {
    await delay(800);
    const submission = simulateCode(sessionId, roundId, language, sourceCode, false);
    updateDb((db) => {
      db.submissions[submission.id] = submission;
    });
    return submission;
  },

  async submitCode(
    sessionId: string,
    roundId: string,
    language: string,
    sourceCode: string,
    onProgress?: (stage: ProgressStage) => void,
  ): Promise<SubmitResult> {
    onProgress?.('received');
    await delay(400);
    const submission = simulateCode(sessionId, roundId, language, sourceCode, true);
    updateDb((db) => {
      db.submissions[submission.id] = submission;
    });
    const db = readDb();
    const session = db.sessions.find((s) => s.id === sessionId);
    if (!session) throw new Error(`未找到面试 ${sessionId}`);
    const round = session.rounds?.find((r) => r.id === roundId);
    if (!round) throw new Error(`未找到轮次 ${roundId}`);
    onProgress?.('evaluating');
    await delay(550);

    const visiblePassed = submission.visibleTestResults.filter((t) => t.passed).length;
    const ratio = visiblePassed / Math.max(1, submission.visibleTestResults.length);
    const score = Math.max(1, Math.min(5, Math.round((1 + ratio * 4) * 10) / 10));
    round.candidateAnswers.push({
      kind: round.candidateAnswers.length === 0 ? 'initial' : 'followup',
      answer: `提交代码：${language} · 可见样例 ${visiblePassed}/${submission.visibleTestResults.length} 通过`,
      submittedAt: nowIso(),
      evaluation: { score, verdict: score >= 3.7 ? 'pass' : 'partial', feedback: '' },
    });
    round.initialScore = round.candidateAnswers[0]?.evaluation?.score ?? score;
    round.score = score;
    round.verdict = score >= 3.7 ? 'pass' : score >= 3.1 ? 'partial' : 'fail';
    round.codeSubmissionId = submission.id;
    round.feedback = score >= 3.7 ? '代码已通过样例与隐藏用例，该能力已获得充分证据。' : '样例未全部通过，注意并发安全与边界条件。';
    round.weakPoint = visiblePassed < submission.visibleTestResults.length ? '实现未覆盖边界条件' : '工程细节待完善';
    round.evaluationSummary = `代码 ${visiblePassed}/${submission.visibleTestResults.length} 通过 · 评分 ${score}`;
    round.status = 'evaluated';
    session.completedQuestionCount += 1;

    const profile = readDb().profiles.find((p) => p.id === session.profileId);
    const next = session.completedQuestionCount < session.maxQuestions ? pickNextQuestion(session, profile) : null;
    if (next) {
      onProgress?.('deciding');
      await delay(300);
      session.rounds = [...(session.rounds ?? []), makeRoundFromBank(next, session, (session.rounds?.length ?? 0) + 1)];
      session.currentRoundSequence = session.rounds.length;
      session.currentDifficulty = next.difficulty;
      session.status = 'awaiting_answer';
      session.updatedAt = nowIso();
      persist(db);
      onProgress?.('next');
      return { session, outcome: { type: 'next', sequence: session.rounds.length } };
    }
    session.status = 'completed';
    session.completedAt = nowIso();
    session.report = buildReport(session);
    session.updatedAt = nowIso();
    persist(db);
    onProgress?.('completed');
    return { session, outcome: { type: 'completed' } };
  },

  async abortSession(sessionId: string): Promise<InterviewSession> {
    await randomDelay();
    updateDb((db) => {
      const session = db.sessions.find((s) => s.id === sessionId);
      if (session) {
        session.status = 'aborted';
        session.abortedAt = nowIso();
        session.updatedAt = nowIso();
      }
    });
    return readDb().sessions.find((s) => s.id === sessionId) as InterviewSession;
  },

  async getReport(sessionId: string) {
    await randomDelay();
    const session = readDb().sessions.find((s) => s.id === sessionId);
    if (!session) throw new Error(`未找到面试 ${sessionId}`);
    if (session.report) return session.report;
    const report = buildReport(session);
    updateDb((db) => {
      const target = db.sessions.find((s) => s.id === sessionId);
      if (target) target.report = report;
    });
    return report;
  },

  getCodeSubmission(id: string): CodeSubmission | undefined {
    return readDb().submissions[id];
  },
};

/* ---------------- 追问与 JD 提取 ---------------- */

function buildFollowup(round: InterviewRound): string {
  const followups: Record<string, string[]> = {
    'go-concurrency': ['请对比 channel 与 mutex 的适用场景，并说明如何排查 goroutine 泄漏。'],
    mysql: ['请说明 EXPLAIN 中 type 字段各取值（ref / range / ALL）的含义，以及回表次数如何估算。'],
    redis: ['如果缓存与数据库同时更新，如何保证一致性？请对比先删缓存与先更 DB 的两种顺序。'],
    kafka: ['请描述一次完整的 rebalance 过程，以及消费端如何避免重复提交位移。'],
    'system-design': ['如果 QPS 再提升 10 倍，你刚才的方案哪一环会先成为瓶颈？如何拆解？'],
    algorithms: ['你的实现最坏时间复杂度是多少？在极端输入下如何优化？'],
    network: ['请说明 TCP 三次握手与 TIME_WAIT 的状态转换，以及高并发下端口耗尽如何规避。'],
  };
  return followups[round.topic]?.[round.followupCount % 2] ?? '请结合你刚才的回答，补充一个具体的边界场景并说明如何处理。';
}

function buildRoundSummary(round: InterviewRound): string {
  const last = round.candidateAnswers[round.candidateAnswers.length - 1];
  const first = round.candidateAnswers[0];
  if (round.candidateAnswers.length > 1 && first?.evaluation && last?.evaluation) {
    return `初始 ${first.evaluation.score} → 追问后 ${last.evaluation.score}（${round.verdict === 'pass' ? '修正' : round.verdict === 'partial' ? '部分修正' : '未达预期'}）`;
  }
  return `${round.score} · ${round.verdict === 'pass' ? '已证明' : round.verdict === 'partial' ? '证据不足' : '存在矛盾'}`;
}

const JD_SKILL_TEMPLATE: Array<{ topic: string; keyword: RegExp; text: string; weight: number; level: string }> = [
  { topic: 'go-concurrency', keyword: /go/i, text: '熟练掌握 Go 语言核心，理解并发模型（GMP）、内存模型与 GC 机制', weight: 0.9, level: 'advanced' },
  { topic: 'mysql', keyword: /mysql|数据库/i, text: '熟悉 MySQL 索引原理与事务隔离级别，能定位并优化慢查询', weight: 0.8, level: 'medium' },
  { topic: 'redis', keyword: /redis|缓存/i, text: '熟悉 Redis 常见缓存问题（穿透/击穿/雪崩）并给出工程化方案', weight: 0.8, level: 'medium' },
  { topic: 'kafka', keyword: /kafka|消息队列|mq/i, text: '理解 Kafka 消息语义，能处理消费堆积与重平衡下的稳定性问题', weight: 0.7, level: 'medium' },
  { topic: 'system-design', keyword: /架构|系统设计|高并发|分布式/i, text: '具备分布式系统设计与高并发架构思路，能应对压测与容量规划', weight: 0.9, level: 'medium' },
  { topic: 'network', keyword: /http|tcp|网络|幂等/i, text: '熟悉 HTTP/TCP 基础，能描述常见网络异常与幂等方案', weight: 0.5, level: 'beginner' },
  { topic: 'container', keyword: /docker|kubernetes|k8s|容器/i, text: '了解 Docker 与 Kubernetes 基本部署与资源管理', weight: 0.3, level: 'beginner' },
];

/** 从任意粘贴的 JD 文本推导结构化要求（演示用启发式提取）。 */
export function deriveJobExtraction(sourceText: string): JobExtraction {
  const matched = JD_SKILL_TEMPLATE.filter((t) => t.keyword.test(sourceText)).slice(0, 7);
  const requirements =
    matched.length > 0
      ? matched.map((t, index) => ({
          requirementId: `req_${String(index + 1).padStart(2, '0')}`,
          text: t.text,
          category: 'must_have' as const,
          skills: [t.topic === 'go-concurrency' ? 'Go' : t.topic],
          topicIds: [t.topic],
          expectedLevel: t.level,
          weight: t.weight,
          evidenceSpan: '任职要求',
          extractionConfidence: 0.9,
          unmapped: false,
        }))
      : demoJobRequirements;
  return {
    requirements,
    unmappedRequirementIds: [],
    extractionVersion: '1.0',
  };
}

/* ---------------- 代码执行模拟 ---------------- */

function simulateCode(
  sessionId: string,
  roundId: string,
  language: string,
  sourceCode: string,
  hidden: boolean,
): CodeSubmission {
  const hasMutex = /mutex|lock|atomic/i.test(sourceCode);
  const hasTimeRefill = /since|now|last|refill|补充/i.test(sourceCode);
  const hasMap = /map\[/i.test(sourceCode);
  const hasList = /list\.|container\/list|双向链/i.test(sourceCode) || /prev|next/i.test(sourceCode);
  const isLRU = /lru/i.test(sourceCode) || hasMap && hasList;

  const baseTests: CodeSubmission['visibleTestResults'] = [
    { index: 0, status: hasMutex || isLRU ? 'pass' : 'fail', passed: hasMutex || isLRU, actual: '', expected: '', runtimeMs: 2 },
    { index: 1, status: hasTimeRefill || isLRU ? 'pass' : 'fail', passed: hasTimeRefill || isLRU, actual: '', expected: '', runtimeMs: 2 },
    { index: 2, status: hasMutex ? 'pass' : 'fail', passed: hasMutex, actual: '', expected: '', runtimeMs: 3 },
    { index: 3, status: 'pass', passed: true, actual: '', expected: '', runtimeMs: 2 },
  ];
  const passed = baseTests.filter((t) => t.passed).length;
  const hiddenPassed = hidden ? (passed >= 4 ? 5 : passed >= 3 ? 4 : Math.max(1, passed)) : 0;
  const id = newId('sub');
  return {
    id,
    sessionId,
    roundId,
    language: (['python', 'go', 'javascript'].includes(language) ? language : 'go') as CodeSubmission['language'],
    executionStatus: 'completed',
    visibleTestResults: baseTests,
    hiddenTestSummary: {
      status: hidden ? (hiddenPassed >= 5 ? 'passed' : 'failed') : undefined,
      passedCount: hidden ? hiddenPassed : 0,
      totalCount: 5,
    },
    passedCount: passed,
    totalCount: 4,
    runtimeMs: 14,
    memoryKb: 1248,
    compilerOutput: 'ok',
  };
}
