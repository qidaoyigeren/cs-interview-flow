import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes as RouterRoutes } from 'react-router';
import AdminCalibration from '../admin/calibration';
import AdminCompetencies from '../admin/competencies';
import AdminFeedback from '../admin/feedback';
import AdminQuality from '../admin/quality';
import AdminSessions from '../admin/sessions';
import AdminExperiments from '../admin/experiments';

jest.mock('@tanstack/react-query', () => ({
  useMutation: () => ({ mutate: jest.fn(), isPending: false }),
  useQueryClient: () => ({ invalidateQueries: jest.fn() }),
}));
jest.mock('@/services/cs-interview-service', () => ({
  __esModule: true,
  default: {
    createExperiment: jest.fn(),
    stopExperiment: jest.fn(),
  },
}));

jest.mock('@/routes', () => ({
  Routes: {
    CsInterview: '/cs-interview',
    CsInterviewConfigure: '/cs-interview/configure',
    CsInterviewKnowledge: '/cs-interview/knowledge',
    CsInterviewResumes: '/cs-interview/resumes',
    CsInterviewJobs: '/cs-interview/jobs',
    CsInterviewAdminQuality: '/cs-interview/admin/quality',
    CsInterviewAdminSessions: '/cs-interview/admin/sessions',
    CsInterviewAdminSessionDetail: '/cs-interview/admin/sessions/detail',
    CsInterviewAdminGovernance: '/cs-interview/admin/governance',
    CsInterviewAdminFeedback: '/cs-interview/admin/feedback',
    CsInterviewAdminExperiments: '/cs-interview/admin/experiments',
    CsInterviewAdminCompetencies: '/cs-interview/admin/competencies',
    CsInterviewAdminCalibration: '/cs-interview/admin/calibration',
  },
}));
jest.mock('@/hooks/use-cs-interview-request', () => ({
  useInterviewAdminQuality: () => ({
    data: {
      windowHours: 24,
      sessionCount: 10,
      sessionSuccessRate: 0.9,
      sessionFailureCount: 1,
      answerRequestCount: 5,
      stageFailureRates: { judge: 0.1 },
      latencyP50P95: { judge: { p50: 120, p95: 400 } },
      tokens: { input: 1000, output: 500 },
      estimatedCostUsd: 0.25,
      evidenceRejectedCount: 0,
      retrievalCount: 8,
      versionDistribution: { plannerVersion: { v1: 10 } },
    },
    isPending: false,
    error: null,
  }),
  useInterviewAdminSessions: () => ({
    data: [
      {
        id: 'session-1',
        tenantId: 'tenant-1',
        status: 'completed',
        plannerVersion: 'cs-interview-planner-v1',
        promptVersion: 'cs-interview-v1',
        currentDifficulty: 'medium',
        completedQuestionCount: 2,
        failureCode: null,
        createdAt: '2026-08-09T00:00:00Z',
      },
    ],
    isPending: false,
    error: null,
  }),
  useInterviewAdminFeedback: () => ({
    data: [
      {
        id: 'fb-1',
        sessionId: 'session-1',
        kind: 'unfair_scoring',
        status: 'open',
        message: 'The score does not match my answer.',
        promptVersion: 'cs-interview-v1',
        plannerVersion: 'cs-interview-planner-v1',
        model: 'fake-model',
        createdAt: '2026-08-09T00:00:00Z',
      },
    ],
    isPending: false,
    error: null,
  }),
  useInterviewAdminQuestions: () => ({ data: [], isPending: false }),
  useInterviewAdminExperiments: () => ({
    data: {
      items: [
        {
          id: 'experiment-1',
          name: 'prompt-v2-production-scenario',
          status: 'gray',
          trafficPercentage: 10,
          createdBy: 'admin-1',
        },
      ],
      active: [],
    },
    isPending: false,
    error: null,
  }),
  useInterviewAdminCompetencies: () => ({
    data: {
      rubricVersion: 'cs-interview-rubric-v2',
      anchorGroupCount: 2,
      levelPolicies: {
        mid: {
          requiredScore: 3,
          minimumHighConfidenceEvidence: 1,
          defaultDifficulty: 'medium',
          expectation: 'Explain mechanisms and trade-offs.',
        },
      },
      roles: {
        go_backend: [
          {
            competencyId: 'go.runtime',
            name: 'Go 运行时与并发',
            weight: 1.4,
            mustHave: true,
            anchorQuestionPolicy: 'anchored',
            scoreAnchorLevels: [0, 1, 2, 3, 4],
          },
        ],
      },
      anchorGroups: [
        {
          anchorGroupId: 'anchor-go_backend-go-runtime',
          competencyId: 'go.runtime',
          difficulty: 'medium',
          questionIds: ['public-fund-context-001'],
        },
      ],
    },
    isPending: false,
    error: null,
  }),
  useInterviewAdminCalibration: () => ({
    data: {
      fixture: {
        metrics: {
          agentHumanExactRatio: 0.875,
          weightedCohensKappa: 0.8,
          lowConfidenceAccuracy: 1,
        },
        sampleCounts: { agentHumanPairs: 8, lowConfidenceCases: 2 },
        insufficient: { agentHumanExactRatio: true, weightedCohensKappa: true, lowConfidenceAccuracy: true },
        confusionMatrix: {
          '3': { '2': 1, '3': 2 },
          '2': { '2': 1 },
          '4': { '4': 2 },
          '0': {},
          '1': {},
        },
        perCompetency: {},
        versions: { rubricVersion: 'cs-interview-rubric-v2', modelVersion: 'deepseek-v3', promptVersion: 'cs-interview-v1' },
      },
      fixtureSource: 'calibration_quality.json',
      fixtureMetadata: { reviewStatus: 'synthetic_ci_only', description: 'Synthetic CI fixture.' },
      annotationCaseCount: 0,
      annotationCases: [],
    },
    isPending: false,
    error: null,
  }),
}));
jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

test('quality page renders aggregated trace metrics', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/admin/quality']}>
      <RouterRoutes>
        <Route path="/cs-interview/admin/quality" element={<AdminQuality />} />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getByText('90.00%')).toBeInTheDocument();
  expect(screen.getByText('0.25')).toBeInTheDocument();
  expect(screen.getAllByText('judge').length).toBeGreaterThan(0);
});

test('sessions page renders the admin session list', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/admin/sessions']}>
      <RouterRoutes>
        <Route path="/cs-interview/admin/sessions" element={<AdminSessions />} />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getByText('session-1')).toBeInTheDocument();
  expect(screen.getByText('cs-interview-planner-v1')).toBeInTheDocument();
});

test('feedback page renders feedback with version linkage', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/admin/feedback']}>
      <RouterRoutes>
        <Route path="/cs-interview/admin/feedback" element={<AdminFeedback />} />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getByText('unfair scoring')).toBeInTheDocument();
  expect(screen.getByText('The score does not match my answer.')).toBeInTheDocument();
  expect(screen.getByText(/cs-interview-v1/)).toBeInTheDocument();
});

test('experiments page exposes active gray releases', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/admin/experiments']}>
      <RouterRoutes>
        <Route path="/cs-interview/admin/experiments" element={<AdminExperiments />} />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getAllByText('prompt-v2-production-scenario').length).toBeGreaterThan(0);
  expect(screen.getByText('10%')).toBeInTheDocument();
});

test('competencies page lists rubric version, competencies and anchor groups', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/admin/competencies']}>
      <RouterRoutes>
        <Route
          path="/cs-interview/admin/competencies"
          element={<AdminCompetencies />}
        />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getAllByText('cs-interview-rubric-v2').length).toBeGreaterThan(0);
  expect(screen.getAllByText('go.runtime').length).toBeGreaterThan(0);
  expect(screen.getByText('must-have')).toBeInTheDocument();
  expect(screen.getAllByText('anchor-go_backend-go-runtime').length).toBeGreaterThan(0);
});

test('calibration page reports agent/human metrics and insufficient flags', () => {
  render(
    <MemoryRouter initialEntries={['/cs-interview/admin/calibration']}>
      <RouterRoutes>
        <Route
          path="/cs-interview/admin/calibration"
          element={<AdminCalibration />}
        />
      </RouterRoutes>
    </MemoryRouter>,
  );
  expect(screen.getByText('0.875')).toBeInTheDocument();
  expect(screen.getByText('Weighted Cohen’s kappa')).toBeInTheDocument();
  expect(screen.getByText(/cs-interview-rubric-v2/)).toBeInTheDocument();
  expect(screen.getByText('synthetic_ci_only')).toBeInTheDocument();
});
