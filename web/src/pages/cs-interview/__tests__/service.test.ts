import {
  camelizeInterviewData,
  streamInterview,
} from '@/services/cs-interview-service';

jest.mock('@/utils/authorization-util', () => ({
  getAuthorization: () => 'Bearer test-token',
}));
jest.mock('@/utils/register-server', () => ({
  registerNextServer: () => ({}),
}));

describe('CS interview candidate transport', () => {
  it('removes private fields recursively before UI state receives data', () => {
    const value = camelizeInterviewData({
      question_text: 'public question',
      reference_answer: 'private answer',
      nested: {
        evaluation_rubric: ['private point'],
        hidden_tests: [{ input: 1 }],
        retrieval_evidence: [{ content: 'private source text' }],
        evidence_sources: [{ document_name: 'public source' }],
      },
    });
    expect(value).toEqual({
      questionText: 'public question',
      nested: { evidenceSources: [{ documentName: 'public source' }] },
    });
    expect(JSON.stringify(value)).not.toContain('private');
  });

  it('creates an operation and emits resumable SSE changes across split chunks', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'id: 4\nevent: answer_received\ndata: {"state_version":2}\n\nid: 5\nevent: eval',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'uating\ndata: {"round_id":"r1"}\n\nid: 6\nevent: followup_question\ndata: {"question":"why"}\n\n',
          ),
        );
        controller.close();
      },
    });
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            operation: { id: 'operation-1', status: 'running' },
            session: { id: 'session-1' },
            events_url:
              '/api/v1/cs-interview/sessions/session-1/events?operation_id=operation-1',
            replayed: false,
          },
        }),
      } as Response)
      .mockResolvedValueOnce({ ok: true, body } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: { id: 'operation-1', status: 'completed' },
        }),
      } as Response);
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      value: fetchMock,
    });
    const events: string[] = [];
    await streamInterview(
      '/test',
      { requestId: 'request-1', stateVersion: 2 },
      (event) => events.push(event.event),
    );
    expect(events).toEqual([
      'answer_received',
      'evaluating',
      'followup_question',
    ]);
    expect(fetchMock.mock.calls[0][1]?.body).toBe(
      '{"request_id":"request-1","state_version":2}',
    );
    expect(fetchMock.mock.calls[1][0]).toContain('after_sequence=0');
    expect(fetchMock.mock.calls[2][0]).toContain('/operations/operation-1');
  });
});
