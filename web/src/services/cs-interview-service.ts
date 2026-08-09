import { Authorization } from '@/constants/authorization';
import {
  CodeSubmission,
  InterviewOperation,
  InterviewStreamEvent,
} from '@/interfaces/database/cs-interview';
import { getAuthorization } from '@/utils/authorization-util';
import { restAPIv1 } from '@/utils/api';
import { convertTheKeysOfTheObjectToSnake } from '@/utils/common-util';
import { registerNextServer } from '@/utils/register-server';
import camelCase from 'lodash/camelCase';

const BaseUrl = `${restAPIv1}/cs-interview`;

const Methods = {
  listProfiles: { url: `${BaseUrl}/profiles`, method: 'get' },
  createProfile: { url: `${BaseUrl}/profiles`, method: 'post' },
  updateProfile: {
    url: (config: { id: string }) => `${BaseUrl}/profiles/${config.id}`,
    method: 'put',
  },
  deleteProfile: {
    url: (config: { id: string }) => `${BaseUrl}/profiles/${config.id}`,
    method: 'delete',
  },
  listJobs: { url: `${BaseUrl}/jobs`, method: 'get' },
  createJob: { url: `${BaseUrl}/jobs`, method: 'post' },
  uploadJob: { url: `${BaseUrl}/jobs/upload`, method: 'post' },
  getJob: {
    url: (config: { id: string }) => `${BaseUrl}/jobs/${config.id}`,
    method: 'get',
  },
  extractJob: {
    url: (config: { id: string }) => `${BaseUrl}/jobs/${config.id}/extract`,
    method: 'post',
  },
  patchJob: {
    url: (config: { id: string }) => `${BaseUrl}/jobs/${config.id}`,
    method: 'patch',
  },
  deleteJob: {
    url: (config: { id: string }) => `${BaseUrl}/jobs/${config.id}`,
    method: 'delete',
  },
  listDatasets: { url: `${BaseUrl}/knowledge/datasets`, method: 'get' },
  getKnowledgeConfig: { url: `${BaseUrl}/knowledge-config`, method: 'get' },
  saveKnowledgeConfig: { url: `${BaseUrl}/knowledge-config`, method: 'put' },
  validateKnowledgeConfig: {
    url: `${BaseUrl}/knowledge-config/validate`,
    method: 'post',
  },
  listSessions: { url: `${BaseUrl}/sessions`, method: 'get' },
  createSession: { url: `${BaseUrl}/sessions`, method: 'post' },
  getSession: {
    url: (config: { id: string }) => `${BaseUrl}/sessions/${config.id}`,
    method: 'get',
  },
  abortSession: {
    url: (config: { id: string }) => `${BaseUrl}/sessions/${config.id}/abort`,
    method: 'post',
  },
  runCode: {
    url: (config: { id: string }) =>
      `${BaseUrl}/sessions/${config.id}/code/run`,
    method: 'post',
  },
  submitCode: {
    url: (config: { id: string }) =>
      `${BaseUrl}/sessions/${config.id}/code/submit`,
    method: 'post',
  },
  getReport: {
    url: (config: { id: string }) => `${BaseUrl}/sessions/${config.id}/report`,
    method: 'get',
  },
  listResumes: { url: `${BaseUrl}/resumes`, method: 'get' },
  getResume: {
    url: (config: { id: string }) => `${BaseUrl}/resumes/${config.id}`,
    method: 'get',
  },
  uploadResume: { url: `${BaseUrl}/resumes`, method: 'post' },
  extractResume: {
    url: (config: { id: string }) =>
      `${BaseUrl}/resumes/${config.id}/extract`,
    method: 'post',
  },
  createProfileFromResume: {
    url: (config: { id: string }) =>
      `${BaseUrl}/resumes/${config.id}/profile`,
    method: 'post',
  },
  patchResume: {
    url: (config: { id: string }) => `${BaseUrl}/resumes/${config.id}`,
    method: 'patch',
  },
  deleteResume: {
    url: (config: { id: string }) => `${BaseUrl}/resumes/${config.id}`,
    method: 'delete',
  },
  adminQualityOverview: {
    url: `${BaseUrl}/admin/quality/overview`,
    method: 'get',
  },
  adminListSessions: {
    url: `${BaseUrl}/admin/sessions`,
    method: 'get',
  },
  adminSessionAudit: {
    url: (config: { id: string }) => `${BaseUrl}/admin/sessions/${config.id}/audit`,
    method: 'get',
  },
  adminSessionReplay: {
    url: (config: { id: string }) => `${BaseUrl}/admin/sessions/${config.id}/replay`,
    method: 'post',
  },
  adminListQuestions: {
    url: `${BaseUrl}/admin/questions`,
    method: 'get',
  },
  adminReview: { url: `${BaseUrl}/admin/review`, method: 'post' },
  adminListFeedback: {
    url: `${BaseUrl}/admin/feedback`,
    method: 'get',
  },
  submitFeedback: {
    url: (config: { sessionId: string }) =>
      `${BaseUrl}/sessions/${config.sessionId}/feedback`,
    method: 'post',
  },
  listExperiments: { url: `${BaseUrl}/admin/experiments`, method: 'get' },
  createExperiment: { url: `${BaseUrl}/admin/experiments`, method: 'post' },
  stopExperiment: {
    url: (config: { id: string }) => `${BaseUrl}/admin/experiments/${config.id}/stop`,
    method: 'post',
  },
} as const;

const csInterviewService = registerNextServer<keyof typeof Methods>(Methods);

type StreamCallback = (event: InterviewStreamEvent) => void;

type OperationEnvelope = {
  operation: InterviewOperation;
  session: unknown;
  eventsUrl: string;
  replayed: boolean;
};

const CandidateForbiddenKeys = new Set([
  'referenceAnswer',
  'evaluationRubric',
  'retrievalEvidence',
  'hiddenTests',
  'judgePrompt',
  'plannerInternalPrompt',
  'systemPrompt',
  'supportingState',
  'sourceCode',
]);

export const camelizeInterviewData = (value: any): any => {
  if (Array.isArray(value)) return value.map(camelizeInterviewData);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !CandidateForbiddenKeys.has(camelCase(key)))
        .map(([key, item]) => [camelCase(key), camelizeInterviewData(item)]),
    );
  }
  return value;
};

const operationEnvelope = async (
  url: string,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<OperationEnvelope> => {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      [Authorization]: getAuthorization(),
    },
    body: JSON.stringify(convertTheKeysOfTheObjectToSnake(payload)),
    signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || `HTTP ${response.status}`);
  }
  const body = await response.json();
  return camelizeInterviewData(body.data) as OperationEnvelope;
};

const parseEventStream = async (
  response: Response,
  onEvent: StreamCallback,
  initialSequence: number,
) => {
  if (!response.body) throw new Error('SSE response has no body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventName = 'message';
  let eventSequence = initialSequence;
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split('\n\n');
    buffer = frames.pop() || '';
    for (const frame of frames) {
      let data = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('id:')) {
          const parsed = Number(line.slice(3).trim());
          if (Number.isSafeInteger(parsed) && parsed >= 0)
            eventSequence = parsed;
        }
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (data) {
        onEvent({
          event: eventName as InterviewStreamEvent['event'],
          data: camelizeInterviewData(JSON.parse(data)),
          sequence: eventSequence,
        });
      }
      eventName = 'message';
    }
    if (done) break;
  }
  return eventSequence;
};

const operationStatus = async (
  operationId: string,
  signal?: AbortSignal,
): Promise<InterviewOperation> => {
  const response = await fetch(`${BaseUrl}/operations/${operationId}`, {
    headers: { [Authorization]: getAuthorization() },
    signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = await response.json();
  return camelizeInterviewData(body.data) as InterviewOperation;
};

const wait = (milliseconds: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });

export async function streamInterview(
  url: string,
  payload: Record<string, unknown>,
  onEvent: StreamCallback,
  signal?: AbortSignal,
) {
  const envelope = await operationEnvelope(url, payload, signal);
  let sequence = 0;
  let reconnects = 0;
  while (true) {
    try {
      const separator = envelope.eventsUrl.includes('?') ? '&' : '?';
      const response = await fetch(
        `${envelope.eventsUrl}${separator}after_sequence=${sequence}`,
        {
          headers: {
            [Authorization]: getAuthorization(),
            ...(sequence ? { 'Last-Event-ID': String(sequence) } : {}),
          },
          signal,
        },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      sequence = await parseEventStream(response, onEvent, sequence);
      const current = await operationStatus(envelope.operation.id, signal);
      if (current.status === 'failed' || current.status === 'cancelled') {
        throw new Error(current.errorCode || `Operation ${current.status}`);
      }
      if (current.status === 'completed') return current;
      reconnects += 1;
      if (reconnects > 20) throw new Error('SSE reconnect limit exceeded');
      await wait(
        Math.min(5000, 250 * 2 ** Math.min(reconnects, 4)),
        signal,
      );
    } catch (error) {
      if (signal?.aborted) throw error;
      const current = await operationStatus(envelope.operation.id, signal);
      if (current.status === 'failed' || current.status === 'cancelled') {
        throw new Error(current.errorCode || `Operation ${current.status}`);
      }
      if (current.status === 'completed') return current;
      reconnects += 1;
      if (reconnects > 20) throw error;
      await wait(Math.min(5000, 250 * 2 ** Math.min(reconnects, 4)), signal);
    }
  }
}

export async function executeInterviewCode(
  sessionId: string,
  payload: Record<string, unknown>,
  hidden: boolean,
): Promise<CodeSubmission> {
  const endpoint = `${BaseUrl}/sessions/${sessionId}/code/${hidden ? 'submit' : 'run'}`;
  const envelope = await operationEnvelope(endpoint, payload);
  while (true) {
    const operation = await operationStatus(envelope.operation.id);
    if (operation.status === 'completed') {
      const submission = operation.resultSummary.submission;
      if (!submission) throw new Error('Code operation returned no submission');
      return submission as CodeSubmission;
    }
    if (operation.status === 'failed' || operation.status === 'cancelled') {
      throw new Error(operation.errorCode || `Code operation ${operation.status}`);
    }
    await wait(500);
  }
}

export const startInterview = (
  sessionId: string,
  payload: Record<string, unknown>,
  onEvent: StreamCallback,
  signal?: AbortSignal,
) =>
  streamInterview(
    `${BaseUrl}/sessions/${sessionId}/start`,
    payload,
    onEvent,
    signal,
  );

export const submitInterviewAnswer = (
  sessionId: string,
  payload: Record<string, unknown>,
  onEvent: StreamCallback,
  signal?: AbortSignal,
) =>
  streamInterview(
    `${BaseUrl}/sessions/${sessionId}/answers`,
    payload,
    onEvent,
    signal,
  );

export default csInterviewService;
