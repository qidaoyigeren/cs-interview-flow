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
      activeRound: {
        id: 'round-2',
        sequence: 2,
        status: 'awaiting_answer',
        category: 'leetcode',
        topic: 'algorithm.core',
        difficulty: 'medium',
        questionText: 'Find two indices whose values sum to the target.',
        candidateAnswers: [],
        followupQuestions: [],
        followupCount: 0,
        evidenceSources: [
          { evidenceId: 'e1', documentName: 'Synthetic sample' },
        ],
        referenceAnswer: 'THIS MUST NEVER RENDER',
        evaluationRubric: ['PRIVATE POINT'],
      },
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
