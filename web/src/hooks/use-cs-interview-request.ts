import {
  CalibrationView,
  CodeSubmission,
  CompetencyCatalogView,
  InterviewAdminSession,
  InterviewDatasetOption,
  InterviewExperimentView,
  InterviewFeedbackItem,
  InterviewJob,
  InterviewKnowledgeBootstrap,
  InterviewKnowledgeConfig,
  InterviewProfile,
  InterviewQualityOverview,
  InterviewReport,
  InterviewResume,
  InterviewSession,
  InterviewSessionAudit,
} from '@/interfaces/database/cs-interview';
import {
  InterviewProfilePayload,
  KnowledgeConfigPayload,
  ResumeProfilePayload,
} from '@/interfaces/request/cs-interview';
import csInterviewService, {
  camelizeInterviewData,
  executeInterviewCode,
} from '@/services/cs-interview-service';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export const CsInterviewKeys = {
  all: ['cs-interview'] as const,
  profiles: () => [...CsInterviewKeys.all, 'profiles'] as const,
  datasets: () => [...CsInterviewKeys.all, 'datasets'] as const,
  knowledge: () => [...CsInterviewKeys.all, 'knowledge'] as const,
  knowledgeBootstrap: () =>
    [...CsInterviewKeys.all, 'knowledge-bootstrap'] as const,
  sessions: () => [...CsInterviewKeys.all, 'sessions'] as const,
  session: (id: string) => [...CsInterviewKeys.sessions(), id] as const,
  report: (id: string) => [...CsInterviewKeys.session(id), 'report'] as const,
  resumes: () => [...CsInterviewKeys.all, 'resumes'] as const,
  resume: (id: string) => [...CsInterviewKeys.resumes(), id] as const,
  jobs: () => [...CsInterviewKeys.all, 'jobs'] as const,
  job: (id: string) => [...CsInterviewKeys.jobs(), id] as const,
  admin: () => [...CsInterviewKeys.all, 'admin'] as const,
  adminQuality: () => [...CsInterviewKeys.admin(), 'quality'] as const,
  adminSessions: (page: number, status: string) =>
    [...CsInterviewKeys.admin(), 'sessions', page, status] as const,
  adminSessionAudit: (id: string) =>
    [...CsInterviewKeys.admin(), 'audit', id] as const,
  adminQuestions: () => [...CsInterviewKeys.admin(), 'questions'] as const,
  adminFeedback: () => [...CsInterviewKeys.admin(), 'feedback'] as const,
  adminExperiments: () => [...CsInterviewKeys.admin(), 'experiments'] as const,
  adminCompetencies: () => [...CsInterviewKeys.admin(), 'competencies'] as const,
  adminCalibration: () => [...CsInterviewKeys.admin(), 'calibration'] as const,
};

const responseData = <T>(response: any): T =>
  camelizeInterviewData(response.data.data);

export function useInterviewProfiles() {
  return useQuery<InterviewProfile[]>({
    queryKey: CsInterviewKeys.profiles(),
    queryFn: async () => responseData(await csInterviewService.listProfiles()),
    initialData: [],
  });
}

export function useInterviewDatasets() {
  return useQuery<InterviewDatasetOption[]>({
    queryKey: CsInterviewKeys.datasets(),
    queryFn: async () => responseData(await csInterviewService.listDatasets()),
    initialData: [],
  });
}

export function useInterviewKnowledgeConfig() {
  return useQuery<InterviewKnowledgeConfig | null>({
    queryKey: CsInterviewKeys.knowledge(),
    queryFn: async () =>
      responseData(await csInterviewService.getKnowledgeConfig({}, true)),
  });
}

export function useInterviewKnowledgeBootstrap() {
  return useQuery<InterviewKnowledgeBootstrap | null>({
    queryKey: CsInterviewKeys.knowledgeBootstrap(),
    queryFn: async () => {
      const current = responseData<InterviewKnowledgeBootstrap | null>(
        await csInterviewService.getKnowledgeBootstrap({}, true),
      );
      if (current) return current;
      return responseData(
        await csInterviewService.ensureKnowledgeBootstrap({}, true),
      );
    },
    refetchInterval: (query) =>
      query.state.data &&
      !['ready', 'failed'].includes(query.state.data.status)
        ? 3000
        : false,
  });
}

export function useInterviewSessions() {
  return useQuery<InterviewSession[]>({
    queryKey: CsInterviewKeys.sessions(),
    queryFn: async () => responseData(await csInterviewService.listSessions()),
    initialData: [],
  });
}

export function useInterviewSession(id: string) {
  return useQuery<InterviewSession>({
    queryKey: CsInterviewKeys.session(id),
    queryFn: async () =>
      responseData(await csInterviewService.getSession({ id }, true)),
    enabled: Boolean(id),
    refetchOnWindowFocus: true,
  });
}

export function useInterviewReport(id: string) {
  return useQuery<InterviewReport>({
    queryKey: CsInterviewKeys.report(id),
    queryFn: async () =>
      responseData(await csInterviewService.getReport({ id }, true)),
    enabled: Boolean(id),
  });
}

export function useInterviewResumes() {
  return useQuery<InterviewResume[]>({
    queryKey: CsInterviewKeys.resumes(),
    queryFn: async () => responseData(await csInterviewService.listResumes()),
    initialData: [],
  });
}

export function useInterviewResume(id: string) {
  return useQuery<InterviewResume>({
    queryKey: CsInterviewKeys.resume(id),
    queryFn: async () =>
      responseData(await csInterviewService.getResume({ id }, true)),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data?.parseStatus === 'parsing' ? 3000 : false,
  });
}

export function useInterviewJobs() {
  return useQuery<InterviewJob[]>({
    queryKey: CsInterviewKeys.jobs(),
    queryFn: async () => responseData(await csInterviewService.listJobs()),
    initialData: [],
  });
}

export function useInterviewJob(id: string) {
  return useQuery<InterviewJob>({
    queryKey: CsInterviewKeys.job(id),
    queryFn: async () =>
      responseData(await csInterviewService.getJob({ id }, true)),
    enabled: Boolean(id),
  });
}

export function useInterviewAdminQuality() {
  return useQuery<InterviewQualityOverview>({
    queryKey: CsInterviewKeys.adminQuality(),
    queryFn: async () =>
      responseData(await csInterviewService.adminQualityOverview({}, true)),
    refetchInterval: 60000,
  });
}

export function useInterviewAdminSessions(page: number, status: string) {
  return useQuery<InterviewAdminSession[]>({
    queryKey: CsInterviewKeys.adminSessions(page, status),
    queryFn: async () =>
      responseData(
        await csInterviewService.adminListSessions(
          { params: { page, page_size: 20, status: status || undefined } },
          true,
        ),
      ),
    initialData: [],
  });
}

export function useInterviewAdminSessionAudit(id: string) {
  return useQuery<InterviewSessionAudit>({
    queryKey: CsInterviewKeys.adminSessionAudit(id),
    queryFn: async () =>
      responseData(
        await csInterviewService.adminSessionAudit({ id }, true),
      ),
    enabled: Boolean(id),
  });
}

export function useInterviewAdminQuestions() {
  return useQuery<Array<Record<string, any>>>({
    queryKey: CsInterviewKeys.adminQuestions(),
    queryFn: async () =>
      responseData(await csInterviewService.adminListQuestions({}, true)),
    initialData: [],
  });
}

export function useInterviewAdminFeedback() {
  return useQuery<InterviewFeedbackItem[]>({
    queryKey: CsInterviewKeys.adminFeedback(),
    queryFn: async () =>
      responseData(await csInterviewService.adminListFeedback({}, true)),
    initialData: [],
  });
}

export function useInterviewAdminExperiments() {
  return useQuery<{
    items: InterviewExperimentView[];
    active: Array<{ id: string; name: string; trafficPercentage: number }>;
  }>({
    queryKey: CsInterviewKeys.adminExperiments(),
    queryFn: async () =>
      responseData(await csInterviewService.listExperiments({}, true)),
    initialData: { items: [], active: [] },
  });
}

export function useInterviewAdminCompetencies() {
  return useQuery<CompetencyCatalogView>({
    queryKey: CsInterviewKeys.adminCompetencies(),
    queryFn: async () =>
      responseData(await csInterviewService.adminCompetencies({}, true)),
  });
}

export function useInterviewAdminCalibration() {
  return useQuery<CalibrationView>({
    queryKey: CsInterviewKeys.adminCalibration(),
    queryFn: async () =>
      responseData(await csInterviewService.adminCalibration({}, true)),
    refetchInterval: 60000,
  });
}

export function useInterviewMutations() {
  const queryClient = useQueryClient();
  const createProfile = useMutation<
    InterviewProfile,
    Error,
    InterviewProfilePayload
  >({
    mutationFn: async (payload) =>
      responseData(await csInterviewService.createProfile(payload)),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.profiles() }),
  });
  const saveKnowledge = useMutation<
    InterviewKnowledgeConfig,
    Error,
    KnowledgeConfigPayload
  >({
    mutationFn: async (payload) =>
      responseData(await csInterviewService.saveKnowledgeConfig(payload)),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.knowledge() }),
  });
  const validateKnowledge = useMutation<
    Record<string, any>,
    Error,
    KnowledgeConfigPayload
  >({
    mutationFn: async (payload) =>
      responseData(await csInterviewService.validateKnowledgeConfig(payload)),
  });
  const retryKnowledgeBootstrap = useMutation<
    InterviewKnowledgeBootstrap,
    Error,
    void
  >({
    mutationFn: async () =>
      responseData(await csInterviewService.retryKnowledgeBootstrap({}, true)),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: CsInterviewKeys.knowledgeBootstrap(),
      });
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.datasets() });
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.knowledge() });
    },
  });
  const createSession = useMutation<
    InterviewSession,
    Error,
    { profileId: string; knowledgeConfigId: string }
  >({
    mutationFn: async (payload) =>
      responseData(await csInterviewService.createSession(payload)),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.sessions() }),
  });
  const runCode = useMutation<
    CodeSubmission,
    Error,
    { id: string; language: string; sourceCode: string }
  >({
    mutationFn: async (payload) =>
      executeInterviewCode(
        payload.id,
        { ...payload, requestId: crypto.randomUUID() },
        false,
      ),
  });
  const submitCode = useMutation<
    CodeSubmission,
    Error,
    { id: string; language: string; sourceCode: string }
  >({
    mutationFn: async (payload) =>
      executeInterviewCode(
        payload.id,
        { ...payload, requestId: crypto.randomUUID() },
        true,
      ),
  });
  const abortSession = useMutation<
    InterviewSession,
    Error,
    { id: string; stateVersion: number }
  >({
    mutationFn: async (payload) =>
      responseData(
        await csInterviewService.abortSession({
          ...payload,
          requestId: crypto.randomUUID(),
        }),
      ),
  });
  const uploadResume = useMutation<
    InterviewResume,
    Error,
    { formData: FormData }
  >({
    mutationFn: async ({ formData }) =>
      responseData(await csInterviewService.uploadResume({ data: formData }, true)),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.resumes() }),
  });
  const extractResume = useMutation<
    InterviewResume,
    Error,
    { id: string; force?: boolean }
  >({
    mutationFn: async ({ id, force }) =>
      responseData(await csInterviewService.extractResume({ id, force })),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({
        queryKey: CsInterviewKeys.resume(variables.id),
      }),
  });
  const createProfileFromResume = useMutation<
    InterviewProfile,
    Error,
    { id: string; payload: ResumeProfilePayload }
  >({
    mutationFn: async ({ id, payload }) =>
      responseData(
        await csInterviewService.createProfileFromResume({ id, ...payload }),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.profiles() }),
  });
  const deleteResume = useMutation<{ deleted: boolean }, Error, { id: string }>({
    mutationFn: async ({ id }) =>
      responseData(await csInterviewService.deleteResume({ id })),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.resumes() }),
  });
  const patchResume = useMutation<
    InterviewResume,
    Error,
    { id: string; extraction: unknown }
  >({
    mutationFn: async ({ id, extraction }) =>
      responseData(await csInterviewService.patchResume({ id, extraction })),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({
        queryKey: CsInterviewKeys.resume(variables.id),
      }),
  });
  const createJob = useMutation<
    InterviewJob,
    Error,
    { name: string; sourceType: 'paste'; sourceText: string }
  >({
    mutationFn: async (payload) =>
      responseData(await csInterviewService.createJob(payload)),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.jobs() }),
  });
  const uploadJob = useMutation<InterviewJob, Error, { formData: FormData }>({
    mutationFn: async ({ formData }) =>
      responseData(await csInterviewService.uploadJob({ data: formData }, true)),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.jobs() }),
  });
  const extractJob = useMutation<
    InterviewJob,
    Error,
    { id: string; force?: boolean }
  >({
    mutationFn: async ({ id, force }) =>
      responseData(await csInterviewService.extractJob({ id, force })),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.jobs() });
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.job(variables.id) });
    },
  });
  const patchJob = useMutation<
    InterviewJob,
    Error,
    { id: string; extraction: unknown }
  >({
    mutationFn: async ({ id, extraction }) =>
      responseData(await csInterviewService.patchJob({ id, extraction })),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.jobs() });
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.job(variables.id) });
    },
  });
  const deleteJob = useMutation<{ deleted: boolean }, Error, { id: string }>({
    mutationFn: async ({ id }) =>
      responseData(await csInterviewService.deleteJob({ id })),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: CsInterviewKeys.jobs() }),
  });
  return {
    createProfile,
    saveKnowledge,
    validateKnowledge,
    retryKnowledgeBootstrap,
    createSession,
    runCode,
    submitCode,
    abortSession,
    uploadResume,
    extractResume,
    createProfileFromResume,
    deleteResume,
    patchResume,
    createJob,
    uploadJob,
    extractJob,
    patchJob,
    deleteJob,
  };
}
