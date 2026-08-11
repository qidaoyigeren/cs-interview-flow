/**
 * localStorage 持久化层：演示数据存储 + 读改写。
 * 结构上模拟真实后端返回的集合，保证 mock 与真实 API 的对象形状一致。
 */
import type {
  CodeSubmission,
  InterviewDatasetOption,
  InterviewJob,
  InterviewKnowledgeConfig,
  InterviewProfile,
  InterviewResume,
  InterviewSession,
} from '@/lib/types';
import {
  demoDatasets,
  demoJob,
  demoKnowledgeConfig,
  demoProfile,
  demoResume,
  demoSessionActive,
  demoSessionCompleted,
  demoSubmission,
} from './demo';

const DB_KEY = 'cs_interview_agent_db_v2';
const DB_VERSION = 2;

export interface DbShape {
  version: number;
  seededAt: string;
  resumes: InterviewResume[];
  jobs: InterviewJob[];
  profiles: InterviewProfile[];
  sessions: InterviewSession[];
  submissions: Record<string, CodeSubmission>;
  datasets: InterviewDatasetOption[];
  knowledgeConfig: InterviewKnowledgeConfig | null;
  onboarded: boolean;
}

export function emptyDb(): DbShape {
  return {
    version: DB_VERSION,
    seededAt: new Date(0).toISOString(),
    resumes: [],
    jobs: [],
    profiles: [],
    sessions: [],
    submissions: {},
    datasets: [],
    knowledgeConfig: null,
    onboarded: false,
  };
}

export function seedDemo(): DbShape {
  const now = new Date().toISOString();
  return {
    version: DB_VERSION,
    seededAt: now,
    resumes: [demoResume],
    jobs: [demoJob],
    profiles: [demoProfile],
    sessions: [demoSessionCompleted, demoSessionActive],
    submissions: { [demoSubmission.id]: demoSubmission },
    datasets: demoDatasets,
    knowledgeConfig: demoKnowledgeConfig,
    onboarded: false,
  };
}

export function readDb(): DbShape {
  try {
    const raw = localStorage.getItem(DB_KEY);
    if (raw == null) {
      const seeded = seedDemo();
      persist(seeded);
      return seeded;
    }
    const parsed = JSON.parse(raw) as DbShape;
    if (parsed.version !== DB_VERSION) {
      // 版本升级时重置为演示数据，避免结构漂移
      const seeded = seedDemo();
      persist(seeded);
      return seeded;
    }
    return parsed;
  } catch {
    const seeded = seedDemo();
    persist(seeded);
    return seeded;
  }
}

export function persist(db: DbShape): void {
  try {
    localStorage.setItem(DB_KEY, JSON.stringify(db));
  } catch {
    // localStorage 不可用（隐私模式等）时静默降级为内存态
  }
}

export function updateDb(mutator: (db: DbShape) => void): DbShape {
  const db = readDb();
  mutator(db);
  persist(db);
  return db;
}

/** 重置所有数据（重新引导用）。 */
export function resetDb(): void {
  try {
    localStorage.removeItem(DB_KEY);
  } catch {
    // ignore
  }
}

export function upsert<T extends { id: string }>(list: T[], item: T): T[] {
  const index = list.findIndex((entry) => entry.id === item.id);
  if (index >= 0) {
    const next = [...list];
    next[index] = item;
    return next;
  }
  return [item, ...list];
}

export function newId(prefix: string): string {
  const rand = Math.random().toString(36).slice(2, 8);
  return `${prefix}_${Date.now().toString(36)}_${rand}`;
}
