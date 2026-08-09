import {
  InterviewCategory,
  InterviewDifficulty,
} from '@/interfaces/database/cs-interview';

export interface InterviewProfilePayload {
  name: string;
  targetRole: string;
  targetLevel: string;
  technologyStack: string[];
  focusTopics: string[];
  excludedTopics: string[];
  initialDifficulty: InterviewDifficulty;
  preferredCategories: InterviewCategory[];
  questionCount: number;
  maxFollowups: number;
  resumeId: string;
  jobId: string;
}

export interface ResumeProfilePayload
  extends Partial<Omit<InterviewProfilePayload, 'jobId'>> {
  name?: string;
  resumeId?: string;
  jobId: string;
}

export interface KnowledgeConfigPayload {
  id?: string;
  interviewExperienceDatasetId: string;
  leetcodeDatasetId: string;
  fundamentalsDatasetId: string;
  enabled: boolean;
}
