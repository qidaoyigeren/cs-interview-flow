import { InterviewKnowledgeConfig } from '@/interfaces/database/cs-interview';
import { InterviewProfilePayload } from '@/interfaces/request/cs-interview';

export function validateInterviewConfiguration(
  profile: InterviewProfilePayload,
  knowledge?: InterviewKnowledgeConfig | null,
) {
  const errors: string[] = [];
  if (!profile.name.trim()) errors.push('name');
  if (!profile.targetRole) errors.push('targetRole');
  if (!profile.targetLevel) errors.push('targetLevel');
  if (!profile.resumeId) errors.push('resumeId');
  if (!profile.jobId) errors.push('jobId');
  if (profile.questionCount < 1 || profile.questionCount > 20) {
    errors.push('questionCount');
  }
  if (profile.maxFollowups < 0 || profile.maxFollowups > 5) {
    errors.push('maxFollowups');
  }
  const excludedTopics = new Set(profile.excludedTopics);
  if (profile.focusTopics.some((topic) => excludedTopics.has(topic))) {
    errors.push('topicConflict');
  }
  if (!knowledge?.enabled) errors.push('knowledge');
  const ids = knowledge
    ? [
        knowledge.interviewExperienceDatasetId,
        knowledge.leetcodeDatasetId,
        knowledge.fundamentalsDatasetId,
      ]
    : [];
  if (ids.length !== 3 || new Set(ids).size !== 3 || ids.some((id) => !id)) {
    errors.push('datasets');
  }
  return errors;
}
