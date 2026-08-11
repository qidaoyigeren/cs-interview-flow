/**
 * 报告生成器：面试完成后，从轮次数据动态推导能力评分、JD 验证矩阵、技能核验与训练计划。
 * 供新面试完成后自动生成报告使用；演示数据中的报告为手工校准版本。
 */
import type {
  InterviewReport,
  InterviewRound,
  InterviewSession,
  JDRequirement,
  JDVerificationItem,
  SkillVerificationItem,
} from '@/lib/types';
import { readDb } from './db';

const TOPIC_LABEL: Record<string, string> = {
  'go-concurrency': 'Go 并发',
  mysql: 'MySQL',
  redis: '缓存',
  kafka: 'Kafka',
  'system-design': '系统设计',
  algorithms: '算法',
  network: '网络',
  container: '容器',
  frontend: '前端',
};

const avg = (values: number[]) =>
  values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : 0;

const round1 = (value: number) => Math.round(value * 10) / 10;

export function buildReport(session: InterviewSession): InterviewReport {
  const rounds = (session.rounds ?? []).filter(
    (r): r is InterviewRound & { score: number } => r.status === 'evaluated' && r.score != null,
  );
  const db = readDb();
  const profile = db.profiles.find((p) => p.id === session.profileId);
  const job = session.job?.id ? db.jobs.find((j) => j.id === session.job?.id) : undefined;
  const requirements = job?.extraction?.requirements ?? [];

  /* 能力评分：按主题聚合，0-5 → 0-10 */
  const abilityScores: Record<string, number> = {};
  for (const round of rounds) {
    const label = TOPIC_LABEL[round.topic] ?? round.topic;
    const current = abilityScores[label] ?? 0;
    const count = abilityScores[`__count_${label}`] ?? 0;
    abilityScores[label] = round1((current * count + round.score) / (count + 1));
    abilityScores[`__count_${label}`] = count + 1;
  }
  const cleanAbility: Record<string, number> = {};
  for (const [key, value] of Object.entries(abilityScores)) {
    if (!key.startsWith('__count_')) cleanAbility[key] = value;
  }

  const sorted = Object.entries(cleanAbility).sort((a, b) => b[1] - a[1]);
  const strengths = sorted.slice(0, 2).map(([topic, score]) => ({ topic, score }));
  const weaknesses = [...sorted].reverse().slice(0, 3).map(([topic, score], index) => ({
    topic,
    score,
    priority: index + 1,
  }));

  /* 技能核验：从简历声称技能出发，关联被考察的轮次 */
  const skillVerification: SkillVerificationItem[] = [];
  const resume = profile?.resumeId ? db.resumes.find((r) => r.id === profile.resumeId) : undefined;
  for (const claim of resume?.extraction?.claimedSkills ?? []) {
    const related = rounds.filter(
      (r) => (r.resumeProbe?.skills ?? []).includes(claim.skill) || r.topic === claim.skill,
    );
    const scores = related.map((r) => r.score);
    const average = scores.length ? avg(scores) : null;
    const hasFail = related.some((r) => r.verdict === 'fail');
    const status: SkillVerificationItem['status'] =
      scores.length === 0
        ? 'not_tested'
        : hasFail
          ? 'disputed'
          : average != null && average >= 3.6
            ? 'verified'
            : 'partial';
    skillVerification.push({
      skill: claim.skill,
      claimedLevel: claim.claimedLevel,
      topics: claim.topics,
      testedRoundCount: related.length,
      avgScore: average == null ? null : round1(average),
      status,
      recommendation: statusToRecommendation(status, claim.skill),
    });
  }

  /* JD 验证矩阵 */
  const jdVerificationMatrix: JDVerificationItem[] = requirements.map((req) => {
    const actualQuestions = rounds
      .filter((r) => r.targetRequirementId === req.requirementId)
      .map((r) => ({
        roundId: r.id,
        questionId: r.questionId,
        questionText: r.questionText,
        topic: r.topic,
      }));
    const scores = actualQuestions.map((q) => rounds.find((r) => r.id === q.roundId)?.score ?? 0);
    const score = scores.length ? round1(avg(scores)) : null;
    const allStrong = scores.length > 0 && scores.every((s) => s >= 3.6);
    const anyFail = rounds.some(
      (r) => r.targetRequirementId === req.requirementId && r.verdict === 'fail',
    );
    const status: JDVerificationItem['verificationStatus'] =
      scores.length === 0 ? 'untested' : anyFail ? 'disputed' : allStrong ? 'verified' : 'partial';
    const claimMatched = (resume?.extraction?.claimedSkills ?? []).some((c) =>
      req.skills.some((s) => s === c.skill || c.skill.includes(s) || s.includes(c.skill)),
    );
    return {
      requirementId: req.requirementId,
      requirementText: req.text,
      category: req.category,
      weight: req.weight,
      resumeClaimStatus: claimMatched
        ? ('matched' as const)
        : req.category === 'nice_to_have'
          ? ('missing' as const)
          : ('missing' as const),
      resumeEvidence: claimMatched ? [{ claim: '简历已声明相关技能' }] : [],
      actualQuestions,
      score,
      verificationStatus: status,
      supportEvidence: actualQuestions.map((q) => ({
        roundId: q.roundId,
        questionId: q.questionId,
        evidenceIds: rounds.find((r) => r.id === q.roundId)?.evidenceSources.map((e) => e.evidenceId) ?? [],
        evidenceVersions: [],
        score: rounds.find((r) => r.id === q.roundId)?.score,
      })),
      improvementRecommendation: statusToImprovement(status, req),
      unmapped: req.unmapped,
    };
  });

  /* 总体匹配度：按权重的能力覆盖率 */
  const tested = jdVerificationMatrix.filter((item) => item.score != null);
  const weighted = tested.reduce((sum, item) => sum + item.weight * (item.score ?? 0) * 20, 0);
  const weightSum = tested.reduce((sum, item) => sum + item.weight, 0);
  const overallScore = weightSum > 0 ? Math.round(weighted / weightSum) : 0;

  const metric = (key: string) => {
    const map: Record<string, { sum: number; count: number }> = {};
    for (const round of rounds) {
      const k = (round as unknown as Record<string, unknown>)[key];
      const label = typeof k === 'string' ? k : '';
      if (!label) continue;
      const current = map[label] ?? { sum: 0, count: 0 };
      map[label] = {
        sum: current.sum + round.score,
        count: current.count + 1,
      };
    }
    return Object.fromEntries(
      Object.entries(map).map(([label, v]) => [label, round1(v.sum / v.count)]),
    );
  };

  const initial = rounds
    .map((r) => r.candidateAnswers[0]?.evaluation?.score ?? r.initialScore ?? r.score)
    .filter((v): v is number => v != null);

  const trainingPlan = weaknesses.map((weakness, index) => ({
    order: index + 1,
    topic: weakness.topic,
    action: actionTemplate(weakness.topic),
    successCriteria: '能在追问中稳定给出关键结论，相关题目达到 3.7 分以上。',
  }));

  const markdownRows = Object.entries(cleanAbility)
    .map(([topic, score]) => `| ${topic} | ${score.toFixed(1)} |`)
    .join('\n');

  const report: InterviewReport = {
    id: `rep_${session.id}`,
    sessionId: session.id,
    overallScore,
    starRating: Math.min(5, Math.max(1, Math.round(overallScore / 20))),
    abilityScores: cleanAbility,
    strengths,
    weaknesses,
    trainingPlan,
    metrics: {
      initialAnswerAverage: round1(avg(initial)),
      postFollowupAverage: round1(avg(rounds.map((r) => r.score))),
      difficultyScores: metric('difficulty'),
      categoryScores: metric('category'),
      questionTypeScores: metric('questionType'),
      followupCount: rounds.reduce((sum, r) => sum + r.followupCount, 0),
      questionCount: rounds.length,
      recommendedRole: profile?.targetRole ?? '后端开发',
      recommendedDifficulty: profile?.initialDifficulty ?? 'medium',
    },
    skillVerification,
    jdVerificationMatrix,
    reportMarkdown: `# 面试报告\n\n## 能力评分\n| 能力 | 分数 |\n| --- | --- |\n${markdownRows}\n\n## 训练计划\n${trainingPlan.map((t) => `${t.order}. ${t.topic}：${t.action}`).join('\n')}`,
    reportVersion: '1.0',
  };
  return report;
}

function statusToRecommendation(status: SkillVerificationItem['status'], skill: string): string {
  switch (status) {
    case 'verified':
      return `保持「${skill}」的面试手感，准备相关追问。`;
    case 'partial':
      return `「${skill}」证据不足，建议补强细节后重测。`;
    case 'disputed':
      return `「${skill}」与简历声明存在矛盾，需专项复习。`;
    default:
      return `本轮未考察「${skill}」，建议下一场覆盖。`;
  }
}

function statusToImprovement(status: JDVerificationItem['verificationStatus'], req: JDRequirement): string {
  switch (status) {
    case 'verified':
      return `「${req.text}」已获得充分证据，建议准备更深的追问。`;
    case 'partial':
      return `「${req.text}」覆盖不完整，建议补充细节并重测。`;
    case 'disputed':
      return `「${req.text}」存在矛盾，需要专项复习后重验。`;
    default:
      return `「${req.text}」本轮未考察，建议下一场覆盖。`;
  }
}

function actionTemplate(topic: string): string {
  return `围绕「${topic}」完成一次专项训练：梳理高频追问、背诵关键结论、写一个最小可运行示例。`;
}
