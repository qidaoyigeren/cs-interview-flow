import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes as RouterRoutes } from 'react-router';
import { submitInterviewAnswer } from '@/services/cs-interview-service';
import InterviewSessionPage from '../session';

jest.mock('@monaco-editor/react', () => () => (
  <div data-testid="code-editor" />
));
jest.mock('react-markdown', () => ({ children }: { children: string }) => (
  <>{children}</>
));
jest.mock('@/routes', () => ({
  Routes: {
    CsInterview: '/cs-interview',
    CsInterviewConfigure: '/cs-interview/configure',
    CsInterviewKnowledge: '/cs-interview/knowledge',
    CsInterviewResumes: '/cs-interview/resumes',
    CsInterviewJobs: '/cs-interview/jobs',
    CsInterviewReport: '/cs-interview/report',
    CsInterviewAdminQuality: '/cs-interview/admin/quality',
    CsInterviewAdminSessions: '/cs-interview/admin/sessions',
    CsInterviewAdminGovernance: '/cs-interview/admin/governance',
    CsInterviewAdminFeedback: '/cs-interview/admin/feedback',
    CsInterviewAdminExperiments: '/cs-interview/admin/experiments',
    CsInterviewAdminCompetencies: '/cs-interview/admin/competencies',
    CsInterviewAdminCalibration: '/cs-interview/admin/calibration',
  },
}));
jest.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: jest.fn() }),
}));
jest.mock('@/services/cs-interview-service', () => ({
  submitInterviewAnswer: jest.fn(
    async (
      _id: string,
      _payload: unknown,
      onStreamEvent: (streamEvent: unknown) => void,
    ) => {
      onStreamEvent({ event: 'answer_received', data: { stateVersion: 4 } });
      onStreamEvent({ event: 'followup_question', data: { question: 'Why?' } });
    },
  ),
}));
// Mutable fixture read by the mocked useInterviewSession.  Declared with `var`
// (hoisted, TDZ-free) because the jest.mock factory below runs at import time,
// before the top-level initializer would execute.
// eslint-disable-next-line no-var
var mockActiveRound = {};

jest.mock('@/hooks/use-cs-interview-request', () => ({
  CsInterviewKeys: {
    session: (id: string) => ['cs-interview', 'sessions', id],
  },
  useInterviewSession: () => ({
    data: {
      id: 'session-1',
      status: 'awaiting_answer',
      stateVersion: 3,
      currentDifficulty: 'medium',
      maxQuestions: 8,
      maxFollowups: 2,
      completedQuestionCount: 1,
      currentRoundSequence: 2,
      startedAt: '2026-08-07T00:00:00Z',
      projectAttack: {
        present: true,
        projectId: 'proj-test',
        projectName: 'CS面试Agent',
        attackTargetCount: 6,
        pendingTargetCount: 4,
        verifiedClaimCount: 1,
        claimFollowupLimit: 2,
      },
      activeRound: mockActiveRound,
    },
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  }),
  useInterviewMutations: () => ({
    runCode: { mutateAsync: jest.fn(), isPending: false },
    submitCode: { mutateAsync: jest.fn(), isPending: false },
    abortSession: { mutateAsync: jest.fn(), isPending: false },
  }),
}));

const baseRound = {
  id: 'round-2',
  sequence: 2,
  status: 'awaiting_answer',
  difficulty: 'medium',
  questionText: 'Find two indices whose values sum to the target.',
  candidateAnswers: [],
  followupQuestions: [],
  followupCount: 0,
  resumeProbe: {},
  evidenceSources: [{ evidenceId: 'e1', documentName: 'Synthetic sample' }],
  referenceAnswer: 'THIS MUST NEVER RENDER',
  evaluationRubric: ['PRIVATE POINT'],
};
const leetcodeRound = {
  ...baseRound,
  category: 'leetcode',
  topic: 'algorithm.core',
};
const projectDiveRound = {
  ...baseRound,
  category: 'interview_experience',
  topic: 'backend.distributed',
  questionCategory: 'project',
  projectTarget: {
    targetProjectId: 'proj-test',
    targetClaimId: 'clm-reliable-delivery',
    projectDimension: 'failure',
    projectFollowupDepth: 1,
    claimText: '通过 Redis Lua 租约、ACK Deadline 和 Kafka 实现可靠投递',
    projectName: 'CS面试Agent',
    claimType: 'reliability',
    verificationStatus: 'partial',
    attemptCount: 1,
    followupLimit: 2,
  },
};

const mockSubmitInterviewAnswer = jest.mocked(submitInterviewAnswer);
jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${JSON.stringify(values)}` : key,
  }),
}));

describe('CS interview session recovery', () => {
  beforeAll(() => {
    Object.defineProperty(globalThis, 'crypto', {
      value: { randomUUID: () => 'request-1' },
      configurable: true,
    });
  });

  beforeEach(() => {
    mockSubmitInterviewAnswer.mockClear();
    mockActiveRound = leetcodeRound;
  });

  it('renders the persisted active round and code mode without hidden fields', () => {
    render(
      <MemoryRouter initialEntries={['/cs-interview/session/session-1']}>
        <RouterRoutes>
          <Route
            path="/cs-interview/session/:id"
            element={<InterviewSessionPage />}
          />
        </RouterRoutes>
      </MemoryRouter>,
    );
    expect(
      screen.getByText('Find two indices whose values sum to the target.'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('code-editor')).toBeInTheDocument();
    expect(
      screen.queryByText('THIS MUST NEVER RENDER'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('PRIVATE POINT')).not.toBeInTheDocument();
  });

  it('submits a text answer through the SSE answer request', async () => {
    render(
      <MemoryRouter initialEntries={['/cs-interview/session/session-1']}>
        <RouterRoutes>
          <Route
            path="/cs-interview/session/:id"
            element={<InterviewSessionPage />}
          />
        </RouterRoutes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText('csInterview.session.yourAnswer'), {
      target: { value: 'Use a hash map to retain each value index.' },
    });
    fireEvent.click(
      screen.getByRole('button', {
        name: 'csInterview.session.submitAnswer',
      }),
    );
    await waitFor(() =>
      expect(mockSubmitInterviewAnswer).toHaveBeenCalledWith(
        'session-1',
        {
          requestId: 'request-1',
          answer: 'Use a hash map to retain each value index.',
          stateVersion: 3,
        },
        expect.any(Function),
      ),
    );
  });

  it('renders the project deep-dive panel without leaking planner internals', () => {
    mockActiveRound = projectDiveRound;
    render(
      <MemoryRouter initialEntries={['/cs-interview/session/session-1']}>
        <RouterRoutes>
          <Route
            path="/cs-interview/session/:id"
            element={<InterviewSessionPage />}
          />
        </RouterRoutes>
      </MemoryRouter>,
    );
    expect(screen.getByText('csInterview.session.projectDive')).toBeInTheDocument();
    expect(screen.getByText('CS面试Agent')).toBeInTheDocument();
    // Internal planner weights / scoring points must never reach the page.
    expect(screen.queryByText('priority')).not.toBeInTheDocument();
    expect(screen.queryByText('decision_audit')).not.toBeInTheDocument();
  });

  it('never labels a foundation round as a project deep-dive', () => {
    mockActiveRound = {
      ...baseRound,
      category: 'interview_experience',
      topic: 'backend.distributed',
      questionCategory: 'foundation',
      projectDiveDowngraded: true,
      projectTarget: undefined,
    };
    render(
      <MemoryRouter initialEntries={['/cs-interview/session/session-1']}>
        <RouterRoutes>
          <Route
            path="/cs-interview/session/:id"
            element={<InterviewSessionPage />}
          />
        </RouterRoutes>
      </MemoryRouter>,
    );
    // Even though the session has an attack map, a foundation round must show
    // the foundation panel and never the project deep-dive panel.
    expect(
      screen.queryByText('csInterview.session.projectDive'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('csInterview.session.foundationVerify'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('csInterview.session.foundationDowngraded'),
    ).toBeInTheDocument();
  });

  it('renders a disconnected state and preserves an idempotent retry action', async () => {
    mockSubmitInterviewAnswer.mockRejectedValueOnce(new Error('offline'));
    render(
      <MemoryRouter initialEntries={['/cs-interview/session/session-1']}>
        <RouterRoutes>
          <Route
            path="/cs-interview/session/:id"
            element={<InterviewSessionPage />}
          />
        </RouterRoutes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText('csInterview.session.yourAnswer'), {
      target: { value: 'Retry this answer safely.' },
    });
    fireEvent.click(
      screen.getByRole('button', {
        name: 'csInterview.session.submitAnswer',
      }),
    );
    expect(await screen.findByText('offline')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'csInterview.session.retry' }),
    );
    await waitFor(() =>
      expect(mockSubmitInterviewAnswer).toHaveBeenCalledTimes(2),
    );
    expect(mockSubmitInterviewAnswer.mock.calls[0][1]).toEqual(
      mockSubmitInterviewAnswer.mock.calls[1][1],
    );
  });
});
