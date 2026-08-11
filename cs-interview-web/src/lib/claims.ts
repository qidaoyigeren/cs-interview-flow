/** 高风险声明：简历详情页编辑后持久化，配置页/面试页读取同一来源。 */
import { readStorage } from '@/lib/storage';
import type { HighRiskClaim, ResumeExtraction } from '@/lib/types';

export const hrcKey = (resumeId: string) => `cs_hrc_${resumeId}`;

export function deriveHighRiskClaims(extraction?: ResumeExtraction): HighRiskClaim[] {
  if (!extraction) return [];
  return (extraction.claimedSkills ?? [])
    .filter((skill) => skill.claimedLevel === 'proficient' || skill.claimedLevel === 'fluent')
    .slice(0, 4)
    .map((skill, index) => ({
      id: `hrc_${index + 1}`,
      claim: `熟练使用/深入理解 ${skill.skill}`,
      source: '技能自述',
      reason: '自述等级较高，容易在追问中被验证。请在保存前补充可能被追问的边界细节。',
      topics: skill.topics,
    }));
}

export function readHighRiskClaims(resumeId: string, extraction?: ResumeExtraction): HighRiskClaim[] {
  const stored = readStorage<HighRiskClaim[]>(hrcKey(resumeId), []);
  if (stored.length > 0) return stored;
  return deriveHighRiskClaims(extraction);
}
