import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  InterviewDatasetOption,
  InterviewJob,
  InterviewProfile,
  InterviewReport,
  InterviewResume,
  InterviewSession,
  ResumeExtraction,
} from '@/lib/types';
import { mockApi } from '@/lib/mock/api';
import { readDb, updateDb } from '@/lib/mock/db';

export const CsKeys = {
  all: ['cs-agent'] as const,
  resumes: () => [...CsKeys.all, 'resumes'] as const,
  resume: (id: string) => [...CsKeys.resumes(), id] as const,
  jobs: () => [...CsKeys.all, 'jobs'] as const,
  job: (id: string) => [...CsKeys.jobs(), id] as const,
  profiles: () => [...CsKeys.all, 'profiles'] as const,
  sessions: () => [...CsKeys.all, 'sessions'] as const,
  session: (id: string) => [...CsKeys.sessions(), id] as const,
  report: (id: string) => [...CsKeys.session(id), 'report'] as const,
  datasets: () => [...CsKeys.all, 'datasets'] as const,
  knowledge: () => [...CsKeys.all, 'knowledge'] as const,
  onboarded: () => [...CsKeys.all, 'onboarded'] as const,
};

export function useResumes() {
  return useQuery<InterviewResume[]>({
    queryKey: CsKeys.resumes(),
    queryFn: () => mockApi.listResumes(),
    initialData: [],
    refetchInterval: (query) =>
      (query.state.data ?? []).some((r) => ['parsing', 'pending'].includes(r.parseStatus))
        ? 1200
        : false,
  });
}

export function useResume(id: string) {
  return useQuery<InterviewResume>({
    queryKey: CsKeys.resume(id),
    queryFn: () => mockApi.getResume(id),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.parseStatus === 'parsing' ? 1200 : false),
  });
}

export function useJobs() {
  return useQuery<InterviewJob[]>({
    queryKey: CsKeys.jobs(),
    queryFn: () => mockApi.listJobs(),
    initialData: [],
  });
}

export function useJob(id: string) {
  return useQuery<InterviewJob>({
    queryKey: CsKeys.job(id),
    queryFn: () => mockApi.getJob(id),
    enabled: Boolean(id),
  });
}

export function useProfiles() {
  return useQuery<InterviewProfile[]>({
    queryKey: CsKeys.profiles(),
    queryFn: () => mockApi.listProfiles(),
    initialData: [],
  });
}

export function useSessions() {
  return useQuery<InterviewSession[]>({
    queryKey: CsKeys.sessions(),
    queryFn: () => mockApi.listSessions(),
    initialData: [],
  });
}

export function useSession(id: string) {
  return useQuery<InterviewSession>({
    queryKey: CsKeys.session(id),
    queryFn: () => mockApi.getSession(id),
    enabled: Boolean(id),
    refetchOnWindowFocus: true,
  });
}

export function useReport(id: string) {
  return useQuery<InterviewReport>({
    queryKey: CsKeys.report(id),
    queryFn: () => mockApi.getReport(id),
    enabled: Boolean(id),
  });
}

export function useKnowledgeConfig() {
  return useQuery({
    queryKey: CsKeys.knowledge(),
    queryFn: () => mockApi.getKnowledgeConfig(),
  });
}

export function useDatasets() {
  return useQuery<InterviewDatasetOption[]>({
    queryKey: CsKeys.datasets(),
    queryFn: () => mockApi.listDatasets(),
    initialData: [],
  });
}

export function useOnboarded() {
  return useQuery<boolean>({
    queryKey: CsKeys.onboarded(),
    queryFn: () => readDb().onboarded,
  });
}

/** 标记已完成首次引导。 */
export function useCompleteOnboarding() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      updateDb((db) => {
        db.onboarded = true;
      });
      return true;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CsKeys.onboarded() });
    },
  });
}

export interface ResumeUploadInput {
  file: File;
}

export function useCsMutations() {
  const queryClient = useQueryClient();
  const invalidate = (keys: readonly unknown[]) => {
    queryClient.invalidateQueries({ queryKey: keys });
  };

  const uploadResume = useMutation<InterviewResume, Error, ResumeUploadInput>({
    mutationFn: async ({ file }) => mockApi.uploadResume(file.name, file.type),
    onSuccess: () => invalidate(CsKeys.resumes()),
  });

  const extractResume = useMutation<InterviewResume, Error, { id: string }>({
    mutationFn: async ({ id }) => mockApi.extractResume(id),
    onSuccess: (_data, variables) => invalidate(CsKeys.resume(variables.id)),
  });

  const saveResume = useMutation<InterviewResume, Error, { id: string; extraction: ResumeExtraction }>({
    mutationFn: async ({ id, extraction }) => mockApi.patchResume(id, extraction),
    onSuccess: (_data, variables) => invalidate(CsKeys.resume(variables.id)),
  });

  const deleteResume = useMutation<void, Error, { id: string }>({
    mutationFn: async ({ id }) => mockApi.deleteResume(id),
    onSuccess: () => {
      invalidate(CsKeys.resumes());
      invalidate(CsKeys.profiles());
    },
  });

  const createProfileFromResume = useMutation<InterviewProfile, Error, { id: string }>({
    mutationFn: async ({ id }) => mockApi.createProfileFromResume(id),
    onSuccess: () => invalidate(CsKeys.profiles()),
  });

  const createJob = useMutation<InterviewJob, Error, { name: string; sourceText: string }>({
    mutationFn: async ({ name, sourceText }) => mockApi.createJob(name, sourceText),
    onSuccess: () => invalidate(CsKeys.jobs()),
  });

  const uploadJob = useMutation<InterviewJob, Error, ResumeUploadInput>({
    mutationFn: async ({ file }) => mockApi.uploadJob(file.name),
    onSuccess: () => invalidate(CsKeys.jobs()),
  });

  const extractJob = useMutation<InterviewJob, Error, { id: string }>({
    mutationFn: async ({ id }) => mockApi.extractJob(id),
    onSuccess: (_data, variables) => {
      invalidate(CsKeys.jobs());
      invalidate(CsKeys.job(variables.id));
    },
  });

  const saveJob = useMutation<InterviewJob, Error, { id: string; extraction: InterviewJob['extraction'] }>({
    mutationFn: async ({ id, extraction }) => mockApi.patchJob(id, extraction),
    onSuccess: (_data, variables) => {
      invalidate(CsKeys.jobs());
      invalidate(CsKeys.job(variables.id));
    },
  });

  const deleteJob = useMutation<void, Error, { id: string }>({
    mutationFn: async ({ id }) => mockApi.deleteJob(id),
    onSuccess: () => {
      invalidate(CsKeys.jobs());
      invalidate(CsKeys.profiles());
    },
  });

  const createProfile = useMutation<
    InterviewProfile,
    Error,
    Omit<InterviewProfile, 'id' | 'createdAt' | 'updatedAt'>
  >({
    mutationFn: (payload) => mockApi.createProfile(payload),
    onSuccess: () => invalidate(CsKeys.profiles()),
  });

  const createSession = useMutation<InterviewSession, Error, { profileId: string }>({
    mutationFn: async ({ profileId }) => mockApi.createSession({ profileId }),
    onSuccess: () => invalidate(CsKeys.sessions()),
  });

  const abortSession = useMutation<InterviewSession, Error, { id: string }>({
    mutationFn: async ({ id }) => mockApi.abortSession(id),
    onSuccess: (_data, variables) => invalidate(CsKeys.session(variables.id)),
  });

  const saveKnowledge = useMutation({
    mutationFn: (payload: { enabled: boolean }) => mockApi.saveKnowledgeConfig(payload),
    onSuccess: () => invalidate(CsKeys.knowledge()),
  });

  const seedResume = useMutation<InterviewResume, Error>({
    mutationFn: () => mockApi.seedDemoResume(),
    onSuccess: () => invalidate(CsKeys.resumes()),
  });

  const seedJob = useMutation<InterviewJob, Error>({
    mutationFn: () => mockApi.seedDemoJob(),
    onSuccess: () => invalidate(CsKeys.jobs()),
  });

  const launch = useMutation<InterviewSession, Error, LaunchPayload>({
    mutationFn: (payload) => mockApi.launchInterview(payload),
    onSuccess: () => {
      invalidate(CsKeys.sessions());
      invalidate(CsKeys.profiles());
    },
  });

  return {
    uploadResume,
    extractResume,
    saveResume,
    deleteResume,
    createProfileFromResume,
    createJob,
    uploadJob,
    extractJob,
    saveJob,
    deleteJob,
    createProfile,
    createSession,
    abortSession,
    saveKnowledge,
    seedResume,
    seedJob,
    launch,
  };
}

export interface LaunchPayload {
  resumeId?: string;
  jobId?: string;
  name: string;
  targetRole: string;
  targetLevel: string;
  technologyStack: string[];
  focusTopics: string[];
  excludedTopics: string[];
  initialDifficulty: InterviewProfile['initialDifficulty'];
  preferredCategories: InterviewProfile['preferredCategories'];
  questionCount: number;
  maxFollowups: number;
  enableCodeExecution?: boolean;
}
