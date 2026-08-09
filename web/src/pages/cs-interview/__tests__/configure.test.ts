import { InterviewKnowledgeConfig } from '@/interfaces/database/cs-interview';
import { InterviewProfilePayload } from '@/interfaces/request/cs-interview';
import { validateInterviewConfiguration } from '../validation';

const profile: InterviewProfilePayload = {
  name: 'Go backend practice',
  targetRole: 'go_backend',
  targetLevel: 'mid',
  technologyStack: ['Go'],
  focusTopics: [],
  excludedTopics: [],
  initialDifficulty: 'medium',
  preferredCategories: ['interview_experience', 'leetcode', 'baguwen'],
  questionCount: 8,
  maxFollowups: 2,
  resumeId: 'resume-1',
  jobId: 'job-1',
};

const knowledge = {
  id: 'config-1',
  enabled: true,
  interviewExperienceDatasetId: 'dataset-1',
  leetcodeDatasetId: 'dataset-2',
  fundamentalsDatasetId: 'dataset-3',
} as InterviewKnowledgeConfig;

describe('CS interview configuration validation', () => {
  it('accepts a complete profile and three independent datasets', () => {
    expect(validateInterviewConfiguration(profile, knowledge)).toEqual([]);
  });

  it('blocks start when knowledge is missing or duplicated', () => {
    expect(validateInterviewConfiguration(profile, null)).toContain(
      'knowledge',
    );
    expect(
      validateInterviewConfiguration(profile, {
        ...knowledge,
        leetcodeDatasetId: 'dataset-1',
      }),
    ).toContain('datasets');
  });

  it('validates question and follow-up boundaries', () => {
    expect(
      validateInterviewConfiguration(
        { ...profile, questionCount: 21, maxFollowups: 6 },
        knowledge,
      ),
    ).toEqual(expect.arrayContaining(['questionCount', 'maxFollowups']));
  });

  it('requires an extracted resume and JD binding', () => {
    expect(
      validateInterviewConfiguration(
        { ...profile, resumeId: '', jobId: '' },
        knowledge,
      ),
    ).toEqual(expect.arrayContaining(['resumeId', 'jobId']));
  });
});
