import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes as RouterRoutes } from 'react-router';
import InterviewReportPage from '../report';

jest.mock('react-markdown', () => ({ children }: { children: string }) => (
  <>{children.replace(/^# /, '')}</>
));
jest.mock('@/routes', () => ({
  Routes: {
    CsInterview: '/cs-interview',
    CsInterviewConfigure: '/cs-interview/configure',
    CsInterviewKnowledge: '/cs-interview/knowledge',
    CsInterviewResumes: '/cs-interview/resumes',
    CsInterviewJobs: '/cs-interview/jobs',
    CsInterviewAdminQuality: '/cs-interview/admin/quality',
    CsInterviewAdminSessions: '/cs-interview/admin/sessions',
    CsInterviewAdminGovernance: '/cs-interview/admin/governance',
    CsInterviewAdminFeedback: '/cs-interview/admin/feedback',
    CsInterviewAdminExperiments: '/cs-interview/admin/experiments',
    CsInterviewAdminCompetencies: '/cs-interview/admin/competencies',
    CsInterviewAdminCalibration: '/cs-interview/admin/calibration',
  },
}));
jest.mock('@/hooks/use-cs-interview-request', () => ({
  useInterviewReport: () => ({
    data: {
      id: 'report-1',
      sessionId: 'session-1',
      overallScore: 3.5,
      starRating: 4.5,
      abilityScores: { 'go.runtime': 4, 'database.mysql': 3 },
      strengths: [{ topic: 'go.runtime', score: 4 }],
      weaknesses: [{ topic: 'database.mysql', score: 3, priority: 1 }],
      trainingPlan: [
        {
          order: 1,
          topic: 'database.mysql',
          action: 'Review index boundaries.',
          successCriteria: 'Explain the rubric without prompts.',
        },
      ],
      metrics: {
        initialAnswerAverage: 3,
        postFollowupAverage: 4,
        difficultyScores: { medium: 3.5 },
        categoryScores: { baguwen: 3.5 },
        questionTypeScores: { theory: 3.5 },
        followupCount: 1,
        questionCount: 2,
        recommendedRole: 'go_backend',
        recommendedDifficulty: 'advanced',
      },
      reportMarkdown: '# Evidence-based summary',
      reportVersion: 'v1',
      jdVerificationMatrix: [
        {
          requirementId: 'req-go',
          requirementText: 'Must understand Go channels',
          category: 'must_have',
          weight: 1,
          resumeClaimStatus: 'matched',
          resumeEvidence: [],
          actualQuestions: [],
          score: 4,
          verificationStatus: 'verified',
          supportEvidence: [
            {
              roundId: 'round-1',
              questionId: 'go-channel-1',
              evidenceIds: ['chunk-go'],
              evidenceVersions: [
                { evidenceId: 'chunk-go', datasetId: 'fundamentals' },
              ],
              score: 4,
            },
          ],
          improvementRecommendation: 'Continue practicing edge cases.',
          unmapped: false,
        },
      ],
      competencyVerification: [
        {
          competencyId: 'go.runtime',
          name: 'Go 运行时与并发',
          weight: 1.4,
          mustHave: true,
          status: 'verified',
          score: 4,
          bestScore: 4,
          lowConfidence: false,
          anchorDone: true,
          testedRoundCount: 1,
          conclusion: '锚点题与后续证据均支持该能力。',
          evidenceTrack: [
            { kind: 'jd_requirement', text: '熟悉 Go 并发' },
            { kind: 'anchor_question', questionText: 'Explain channel closing.', questionKind: 'anchor' },
            {
              kind: 'answer_evidence',
              score: 4,
              lowConfidence: false,
              spans: [{ spanId: 's1', text: 'Sending panics' }],
            },
          ],
        },
      ],
      projectClaimVerification: [
        {
          projectId: 'proj-go',
          projectName: '交易网关',
          claimId: 'clm-go',
          claimText: '通过超时与重试保证支付接口可用',
          claimType: 'reliability',
          evidenceSpan: '通过超时与重试保证支付接口可用',
          dimensions: [
            {
              dimension: 'failure',
              status: 'verified',
              attemptCount: 2,
              followupDepth: 1,
              answeredEvidence: [
                { fact: '超时后进入降级兜底', factKind: 'failure_mode', evidenceSpan: '超时后进入降级兜底' },
              ],
              relatedQuestionIds: ['q1'],
            },
          ],
          verificationStatus: 'verified',
          score: 4,
          testedRoundCount: 1,
          conclusion: '候选人以项目相关证据演示了该声明。',
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
  useInterviewSession: () => ({
    data: {
      id: 'session-1',
      rounds: [
        {
          id: 'round-1',
          sequence: 1,
          questionText: 'Explain channel closing.',
          category: 'baguwen',
          topic: 'go.runtime',
          difficulty: 'medium',
          candidateAnswers: [{ kind: 'initial', answer: 'Candidate answer' }],
          score: 4,
          feedback: 'Final safe feedback.',
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
}));
jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

test('renders deterministic final report metrics and persisted rounds', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/report/session-1']}>
      <RouterRoutes>
        <Route
          path="/cs-interview/report/:id"
          element={<InterviewReportPage />}
        />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getAllByText('3.50').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Explain channel closing.').length).toBeGreaterThan(0);
  expect(screen.getByText('Evidence-based summary')).toBeInTheDocument();
  expect(screen.getByText('Must understand Go channels')).toBeInTheDocument();
  expect(screen.getAllByText('go-channel-1: chunk-go').length).toBeGreaterThan(0);
  expect(screen.queryByText(/reference answer/i)).not.toBeInTheDocument();
});

test('renders competency evidence track and statuses without leaking internals', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/report/session-1']}>
      <RouterRoutes>
        <Route
          path="/cs-interview/report/:id"
          element={<InterviewReportPage />}
        />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getByText('能力验证证据轨道')).toBeInTheDocument();
  expect(screen.getByText('Go 运行时与并发')).toBeInTheDocument();
  expect(screen.getAllByText('已验证').length).toBeGreaterThan(0);
  expect(screen.getByText(/Sending panics/)).toBeInTheDocument();
  expect(screen.queryByText('reference_answer')).not.toBeInTheDocument();
  expect(screen.queryByText('evaluation_rubric')).not.toBeInTheDocument();
});

test('renders the project claim verification matrix with evidence and status', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/report/session-1']}>
      <RouterRoutes>
        <Route
          path="/cs-interview/report/:id"
          element={<InterviewReportPage />}
        />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getByText('项目声明验真矩阵')).toBeInTheDocument();
  expect(screen.getByText('交易网关')).toBeInTheDocument();
  expect(screen.getByText('通过超时与重试保证支付接口可用')).toBeInTheDocument();
  expect(screen.getByText('failure')).toBeInTheDocument();
  expect(screen.getByText('超时后进入降级兜底')).toBeInTheDocument();
  // Internal planner weights / scoring points must never reach the report.
  expect(screen.queryByText('priority')).not.toBeInTheDocument();
  expect(screen.queryByText('action_factors')).not.toBeInTheDocument();
});
