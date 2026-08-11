export type InterviewDifficulty = 'beginner' | 'medium' | 'advanced';
export type InterviewCategory = 'interview_experience' | 'leetcode' | 'baguwen';

export type ClaimedLevel = 'fluent' | 'experienced' | 'proficient' | 'familiar' | 'beginner';

export type ClaimType =
  | 'architecture'
  | 'technology_choice'
  | 'mechanism'
  | 'reliability'
  | 'data_design'
  | 'interface'
  | 'metric'
  | 'testing';

export type ClaimRiskFlag =
  | 'vague_metric'
  | 'unexplained_choice'
  | 'happy_path_only'
  | 'keyword_stacking'
  | 'missing_validation';

export interface ClaimedSkill {
  skill: string;
  claimedLevel: ClaimedLevel;
  topics: string[];
}

export interface ResumeProjectClaim {
  claimId: string;
  claimType: ClaimType;
  text: string;
  evidenceSpan: string;
  topicIds: string[];
  skills: string[];
  riskFlags: ClaimRiskFlag[];
}

export interface ResumeProject {
  projectId?: string;
  name: string;
  role: string;
  summary: string;
  skills: string[];
  claims?: ResumeProjectClaim[];
}

export interface ResumeExtraction {
  targetRole?: string;
  targetLevel?: string;
  technologyStack?: string[];
  claimedSkills?: ClaimedSkill[];
  projects?: ResumeProject[];
  yearsOfExperience?: number;
  summary?: string;
  extractionVersion?: string;
}

export type ResumeParseStatus = 'pending' | 'parsing' | 'parsed' | 'failed';

export interface InterviewResume {
  id: string;
  profileId?: string;
  fileName: string;
  fileType: string;
  parseStatus: ResumeParseStatus;
  chunkCount: number;
  extraction?: ResumeExtraction;
  extractedAt?: string;
  needsExtraction?: boolean;
  createdAt: string;
  updatedAt: string;
  preview?: {
    name: string;
    skills: string[];
    projectNames: string[];
  };
}

export type JDRequirementCategory =
  | 'must_have'
  | 'nice_to_have'
  | 'responsibility';

export interface JDRequirement {
  requirementId: string;
  text: string;
  category: JDRequirementCategory;
  skills: string[];
  topicIds: string[];
  expectedLevel: string;
  weight: number;
  evidenceSpan: string;
  extractionConfidence: number;
  unmapped: boolean;
}

export interface JobExtraction {
  requirements: JDRequirement[];
  unmappedRequirementIds: string[];
  extractionVersion: string;
}

export interface InterviewJob {
  id: string;
  name: string;
  sourceType: 'paste' | 'file';
  sourceText?: string;
  extraction?: JobExtraction;
  extractionVersion?: string;
  extractedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface SkillVerificationItem {
  skill: string;
  claimedLevel: ClaimedLevel;
  topics: string[];
  testedRoundCount: number;
  avgScore: number | null;
  status: 'verified' | 'partial' | 'disputed' | 'not_tested';
  recommendation: string;
}

export interface InterviewProfile {
  id: string;
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
  resumeId?: string;
  jobId?: string;
  createdAt: string;
  updatedAt: string;
}

export interface DatasetQuality {
  id: string;
  name: string;
  documentCount: number;
  chunkCount: number;
  parsed: boolean;
  parsingIssues: Array<{ documentId: string; name: string; status: string }>;
  metadataQuality: {
    validMetadataCount: number;
    qualityRatio: number;
    ready: boolean;
    issues: Array<{ questionId?: string; errors: string[] }>;
  };
  updatedAt: string;
}

export interface InterviewKnowledgeConfig {
  id: string;
  interviewExperienceDatasetId: string;
  leetcodeDatasetId: string;
  fundamentalsDatasetId: string;
  retrievalConfigSnapshot: {
    similarityThreshold: number;
    vectorSimilarityWeight: number;
    topN: number;
    topK: number;
    rerankId: string;
  };
  metadataQualitySnapshot: Record<string, DatasetQuality>;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface InterviewDatasetOption {
  id: string;
  name: string;
  documentCount: number;
  chunkCount: number;
  embeddingModel: string;
  readOnly?: boolean;
  updatedAt: string;
}

export type KnowledgeBootstrapStatus =
  | 'pending'
  | 'binding'
  | 'running'
  | 'retry_wait'
  | 'ready'
  | 'failed';

export interface KnowledgeBootstrapProgress {
  total: number;
  imported: number;
  parsed: number;
  chunks: number;
}

export interface InterviewKnowledgeBootstrap {
  id: string;
  corpusVersion: string;
  status: KnowledgeBootstrapStatus;
  currentStage: string;
  progress: Record<string, KnowledgeBootstrapProgress>;
  datasetIds: Record<string, string>;
  attemptCount: number;
  maxAttempts: number;
  errorCode?: string;
  errorMessage?: string;
  startedAt?: string;
  completedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface CandidateAnswer {
  kind: 'initial' | 'followup';
  answer: string;
  submittedAt: string;
  evaluation?: {
    score: number;
    verdict: string;
    feedback: string;
  };
}

export interface InterviewRound {
  id: string;
  sessionId: string;
  sequence: number;
  status: string;
  questionId: string;
  category: InterviewCategory;
  topic: string;
  questionType: 'theory' | 'scenario' | 'coding';
  questionKind?: 'anchor' | 'adaptive' | 'coding';
  competencyId?: string;
  difficulty: InterviewDifficulty;
  questionText: string;
  candidateAnswers: CandidateAnswer[];
  followupQuestions: Array<{
    sequence: number;
    question: string;
    selectedAction?: string;
    reason?: string;
    askedAt: string;
  }>;
  followupCount: number;
  codeSubmissionId?: string;
  resumeProbe?: {
    skills?: string[];
    project?: { name: string; role?: string };
    claim?: {
      claimId?: string;
      claimType?: string;
      dimension?: string;
      text?: string;
    };
  };
  projectTarget?: {
    targetProjectId?: string;
    targetClaimId?: string;
    projectDimension?: string;
    projectFollowupDepth?: number;
    claimText?: string;
    projectName?: string;
    claimType?: string;
    verificationStatus?: ProjectClaimVerificationStatus;
    attemptCount?: number;
    followupLimit?: number;
  };
  /** Deterministic frontend classification: 'project' | 'foundation' | 'anchor' | 'coding'. */
  questionCategory?: 'project' | 'foundation' | 'anchor' | 'coding';
  /** True when a project claim's evidence was missing and the round degraded to a foundation question. */
  projectDiveDowngraded?: boolean;
  /** When a foundation question was pulled by the most recent project's technology. */
  pulledByProject?: { topicId?: string; projectName?: string };
  selectedAction?: string;
  targetRequirementId?: string;
  targetRequirement?: JDRequirement;
  targetTopic?: string;
  questionReason?: string;
  evidenceSources: Array<{
    evidenceId: string;
    datasetId: string;
    documentName?: string;
    source?: string;
    sourceDate?: string;
    qualityScore?: number;
  }>;
  initialScore?: number;
  score?: number;
  verdict?: string;
  judgeConfidence?: number;
  weakPoint?: string;
  feedback?: string;
  nextDifficulty?: InterviewDifficulty;
  evaluationSummary?: string;
}

export interface JDVerificationItem {
  requirementId: string;
  requirementText: string;
  category: JDRequirementCategory;
  weight: number;
  resumeClaimStatus: 'matched' | 'partial' | 'missing' | 'unknown';
  resumeEvidence: Array<Record<string, unknown>>;
  actualQuestions: Array<{
    roundId: string;
    questionId: string;
    questionText: string;
    topic: string;
  }>;
  score: number | null;
  verificationStatus: 'untested' | 'verified' | 'partial' | 'disputed';
  supportEvidence: Array<{
    roundId?: string;
    questionId?: string;
    evidenceIds: string[];
    evidenceVersions: Array<{
      evidenceId: string;
      datasetId?: string;
      documentId?: string;
      sourceDate?: string;
      contentSha256?: string;
    }>;
    score?: number;
  }>;
  improvementRecommendation: string;
  unmapped: boolean;
}

export type CompetencyStatus =
  | 'verified'
  | 'partial'
  | 'insufficient_evidence'
  | 'contradiction'
  | 'uncovered';

export interface CompetencyEvidenceTrackItem {
  kind:
    | 'jd_requirement'
    | 'resume_claim'
    | 'anchor_question'
    | 'adaptive_question'
    | 'answer_evidence';
  text?: string;
  roundId?: string;
  questionText?: string;
  questionKind?: string;
  score?: number | null;
  confidence?: number | null;
  lowConfidence?: boolean;
  spans?: Array<{ spanId: string; text: string }>;
}

export interface CompetencyVerificationItem {
  competencyId: string;
  name: string;
  weight: number;
  mustHave: boolean;
  status: CompetencyStatus;
  score: number | null;
  bestScore: number | null;
  lowConfidence: boolean;
  anchorDone: boolean;
  testedRoundCount: number;
  conclusion: string;
  evidenceTrack: CompetencyEvidenceTrackItem[];
}

export type ProjectClaimVerificationStatus =
  | 'untested'
  | 'partial'
  | 'verified'
  | 'disputed'
  | 'contradiction'
  | 'low_confidence';

export interface ProjectClaimVerificationItem {
  projectId: string;
  projectName: string;
  claimId: string;
  claimText: string;
  claimType: string;
  evidenceSpan: string;
  dimensions: Array<{
    dimension: string;
    status: ProjectClaimVerificationStatus;
    attemptCount: number;
    followupDepth: number;
    answeredEvidence: Array<{ fact: string; factKind: string; evidenceSpan: string }>;
    relatedQuestionIds: string[];
  }>;
  verificationStatus: ProjectClaimVerificationStatus;
  score: number | null;
  testedRoundCount: number;
  conclusion: string;
}

export interface InterviewReport {
  id: string;
  sessionId: string;
  overallScore: number;
  starRating: number;
  abilityScores: Record<string, number>;
  strengths: Array<{ topic: string; score: number }>;
  weaknesses: Array<{ topic: string; score: number; priority: number }>;
  trainingPlan: Array<{
    order: number;
    topic: string;
    action: string;
    successCriteria: string;
  }>;
  metrics: {
    initialAnswerAverage: number;
    postFollowupAverage: number;
    difficultyScores: Record<string, number>;
    categoryScores: Record<string, number>;
    questionTypeScores: Record<string, number>;
    followupCount: number;
    questionCount: number;
    recommendedRole: string;
    recommendedDifficulty: InterviewDifficulty;
  };
  skillVerification?: SkillVerificationItem[];
  jdVerificationMatrix: JDVerificationItem[];
  competencyVerification?: CompetencyVerificationItem[];
  projectClaimVerification?: ProjectClaimVerificationItem[];
  reportMarkdown: string;
  reportVersion: string;
}

export interface InterviewSession {
  id: string;
  profileId: string;
  knowledgeConfigId: string;
  status: string;
  currentDifficulty: InterviewDifficulty;
  maxQuestions: number;
  maxFollowups: number;
  completedQuestionCount: number;
  currentRoundSequence: number;
  stateVersion: number;
  promptVersion: string;
  plannerVersion: string;
  job?: {
    id?: string;
    name?: string;
    unmappedRequirementIds: string[];
  };
  projectAttack?: {
    present: boolean;
    projectId?: string;
    projectName?: string;
    attackTargetCount?: number;
    pendingTargetCount?: number;
    verifiedClaimCount?: number;
    claimFollowupLimit?: number;
  };
  startedAt?: string;
  completedAt?: string;
  abortedAt?: string;
  createdAt: string;
  updatedAt: string;
  rounds?: InterviewRound[];
  activeRound?: InterviewRound;
  report?: InterviewReport;
  failureCode?: string;
}

export interface CodeSubmission {
  id: string;
  sessionId: string;
  roundId: string;
  language: 'python' | 'go' | 'javascript';
  executionStatus: string;
  visibleTestResults: Array<{
    index: number;
    status: string;
    passed: boolean;
    actual: unknown;
    expected: unknown;
    runtimeMs: number;
  }>;
  hiddenTestSummary: {
    status?: string;
    passedCount?: number;
    totalCount?: number;
  };
  passedCount: number;
  totalCount: number;
  runtimeMs: number;
  memoryKb: number;
  compilerOutput?: string;
}

export type InterviewOperationStatus =
  | 'pending'
  | 'running'
  | 'retry_wait'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface InterviewOperation {
  id: string;
  sessionId: string;
  roundId?: string;
  requestId: string;
  operationType: string;
  status: InterviewOperationStatus;
  currentStage: string;
  attemptCount: number;
  maxAttempts: number;
  leaseExpiresAt?: string;
  nextRetryAt?: string;
  deadlineAt: string;
  cancellationRequested: boolean;
  errorCode?: string;
  errorClass?: string;
  resultSummary: Record<string, any>;
}

export interface InterviewStreamEvent {
  event:
    | 'answer_received'
    | 'evaluating'
    | 'feedback'
    | 'followup_question'
    | 'next_question'
    | 'interview_completed'
    | 'error';
  data: Record<string, any>;
  sequence?: number;
}

export interface InterviewQualityOverview {
  windowHours: number;
  sessionCount: number;
  sessionSuccessRate?: number;
  sessionFailureCount: number;
  answerRequestCount: number;
  stageFailureRates: Record<string, number>;
  latencyP50P95: Record<string, { p50?: number; p95?: number }>;
  tokens: { input: number; output: number };
  estimatedCostUsd: number;
  costUnknownCount: number;
  evidenceRejectedCount: number;
  retrievalCount: number;
  evidenceRefusalRate?: number;
  followupRate?: number;
  judgeConsistencyRate?: number;
  jdRequirementCoverage?: number;
  runnerFailureRate?: number;
  sloMetrics: Record<string, number | null>;
  alerts: Array<{
    name: string;
    level: 'warning' | 'critical';
    operator: string;
    target: number;
    value?: number;
    passed?: boolean;
    breached?: boolean;
    insufficient: boolean;
    runbook: string;
  }>;
  versionDistribution: Record<string, Record<string, number>>;
}

export interface InterviewAdminSession {
  id: string;
  tenantId: string;
  status: string;
  plannerVersion: string;
  promptVersion: string;
  currentDifficulty: string;
  completedQuestionCount: number;
  failureCode?: string;
  createdAt: string;
}

export interface InterviewPlannerDecision {
  selectedAction?: string;
  targetRequirementId?: string;
  targetTopic?: string;
  questionKind?: string;
  competencyId?: string;
  actionFactors?: Record<string, number | string>;
  reason?: string;
  decisionAudit?: Record<string, any>;
}

export interface InterviewEvidenceAudit {
  answerSequence?: number;
  score?: number;
  matchedAnchor?: number;
  confidence?: number;
  lowConfidence?: boolean;
  consistencyPassed?: boolean;
  evidenceSpanIds?: string[];
  spanTexts?: string[];
}

export interface InterviewAuditRound {
  sequence: number;
  topic: string;
  competencyId?: string;
  questionKind?: string;
  anchorGroupId?: string;
  rubricVersion?: string;
  category: string;
  difficulty: string;
  questionId: string;
  score?: number;
  verdict?: string;
  targetRequirementId?: string;
  evidenceVersions?: Array<{ evidenceId: string; datasetId?: string }>;
  modelVersion?: string;
  promptVersion?: string;
  plannerActions: InterviewPlannerDecision[];
  evidenceEvaluation?: InterviewEvidenceAudit[];
  answerSummary: string;
}

export interface InterviewSessionAudit {
  sessionId: string;
  status: string;
  stateVersion: number;
  plannerVersion: string;
  promptVersion: string;
  failureCode?: string;
  createdAt: string;
  timeline: Array<{
    eventType: string;
    occurredAt: string;
    status: string;
    errorCode?: string;
    roundId?: string;
    plannerVersion?: string;
    promptVersion?: string;
    durationMs?: number;
    metadata: Record<string, any>;
  }>;
  rounds: InterviewAuditRound[];
}

export interface InterviewReplayResult {
  sessionId: string;
  requestedPlannerVersion: string;
  sessionPlannerVersion: string;
  status: 'deterministic' | 'changed' | 'unsupported_version';
  decisions: Array<{
    roundSequence: number;
    decisionPoint: string;
    original: Record<string, any>;
    replayed: Record<string, any>;
    outcome: 'deterministic' | 'changed';
  }>;
  deterministicCount: number;
  totalCount: number;
  deterministicRatio: number;
}

export interface InterviewFeedbackItem {
  id: string;
  sessionId: string;
  roundId?: string;
  questionId?: string;
  evidenceId?: string;
  kind: string;
  status: string;
  message: string;
  model?: string;
  promptVersion?: string;
  plannerVersion?: string;
  createdAt: string;
}

export interface InterviewExperimentView {
  id: string;
  name: string;
  status: string;
  trafficPercentage: number;
  createdBy?: string;
}

export interface CalibrationMetricView {
  name: string;
  value: number;
  sampleCount: number;
  insufficient: boolean;
}

export interface CalibrationView {
  fixture?: {
    metrics: Record<string, number>;
    sampleCounts: Record<string, number>;
    insufficient: Record<string, boolean>;
    confusionMatrix: Record<string, Record<string, number>>;
    perCompetency: Record<
      string,
      {
        caseCount: number;
        agentHumanExactRatio: number;
        insufficient: boolean;
      }
    >;
    versions: Record<string, string>;
  };
  fixtureSource?: string | null;
  fixtureMetadata?: {
    source?: string;
    reviewStatus?: 'synthetic_ci_only' | 'human_reviewed' | string;
    description?: string;
  } | null;
  annotationCaseCount: number;
  annotationCases: Array<{
    caseId: string;
    role: string;
    competencyId: string;
    rubricVersion: string;
    adjudicatedScore?: number;
    reviewerCount: number;
    status: string;
  }>;
}

export interface CompetencyCatalogView {
  rubricVersion: string;
  anchorGroupCount: number;
  levelPolicies: Record<
    string,
    {
      requiredScore: number;
      minimumHighConfidenceEvidence: number;
      defaultDifficulty: string;
      expectation: string;
    }
  >;
  roles: Record<
    string,
    Array<{
      competencyId: string;
      name: string;
      weight: number;
      mustHave: boolean;
      anchorQuestionPolicy: string;
      scoreAnchorLevels: number[];
    }>
  >;
  anchorGroups: Array<{
    anchorGroupId: string;
    competencyId: string;
    difficulty: string;
    questionIds: string[];
  }>;
}
