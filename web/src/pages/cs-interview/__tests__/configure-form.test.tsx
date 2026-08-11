import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import InterviewConfigure from '../configure';

jest.mock('@/routes', () => ({
  Routes: {
    CsInterview: '/cs-interview',
    CsInterviewConfigure: '/cs-interview/configure',
    CsInterviewKnowledge: '/cs-interview/knowledge',
    CsInterviewResumes: '/cs-interview/resumes',
    CsInterviewJobs: '/cs-interview/jobs',
    CsInterviewSession: '/cs-interview/session',
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
  useInterviewKnowledgeConfig: () => ({
    data: { id: 'knowledge-1', enabled: true },
    isLoading: false,
  }),
  useInterviewResumes: () => ({ data: [] }),
  useInterviewJobs: () => ({ data: [] }),
  useInterviewMutations: () => ({
    createProfile: { mutateAsync: jest.fn() },
    createSession: { mutateAsync: jest.fn() },
  }),
}));

jest.mock('@/services/cs-interview-service', () => ({
  startInterview: jest.fn(),
}));

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('CS interview configuration form', () => {
  it('keeps freely edited list values visible', () => {
    render(
      <MemoryRouter>
        <InterviewConfigure />
      </MemoryRouter>,
    );

    const technologyStack = screen.getByLabelText(
      'csInterview.configure.stack',
    );
    const focusTopics = screen.getByLabelText('csInterview.configure.focus');
    const excludedTopics = screen.getByLabelText(
      'csInterview.configure.exclude',
    );

    fireEvent.change(technologyStack, { target: { value: 'Go,' } });
    expect(technologyStack).toHaveValue('Go,');
    fireEvent.change(technologyStack, {
      target: { value: 'Go, Python, PostgreSQL' },
    });
    fireEvent.change(focusTopics, {
      target: { value: 'go.runtime, database.mysql' },
    });
    fireEvent.change(excludedTopics, {
      target: { value: 'frontend, ml.system' },
    });

    expect(technologyStack).toHaveValue('Go, Python, PostgreSQL');
    expect(focusTopics).toHaveValue('go.runtime, database.mysql');
    expect(excludedTopics).toHaveValue('frontend, ml.system');
  });
});
