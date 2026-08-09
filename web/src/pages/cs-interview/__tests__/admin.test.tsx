import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes as RouterRoutes } from 'react-router';
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
