import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useState } from 'react';
import { mockApi, type ProgressStage } from '@/lib/mock/api';
import { CsKeys } from '@/hooks/use-cs-query';

export const STAGE_TEXT: Record<ProgressStage, string> = {
  received: '回答已收到',
  evaluating: '正在核对回答',
  feedback: '评估反馈已生成',
  deciding: '正在选择下一步',
  followup: '发现需要进一步确认的内容',
  next: '已进入下一题',
  completed: '面试已完成，正在生成报告',
  error: '处理出错，请重试',
};

export type FlowPhase = 'idle' | 'streaming' | 'error';

export interface FlowState {
  phase: FlowPhase;
  stage: ProgressStage | null;
  error: string | null;
}

export function useInterviewFlow(sessionId: string) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<FlowPhase>('idle');
  const [stage, setStage] = useState<ProgressStage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: CsKeys.session(sessionId) });
    queryClient.invalidateQueries({ queryKey: CsKeys.sessions() });
  }, [queryClient, sessionId]);

  const submitAnswer = useMutation({
    mutationFn: async (answer: string) => {
      setPhase('streaming');
      setStage('received');
      setError(null);
      return mockApi.submitAnswer(sessionId, answer, setStage);
    },
    onSuccess: (result) => {
      setPhase('idle');
      setStage(null);
      refresh();
      return result;
    },
    onError: (err: Error) => {
      setPhase('error');
      setError(err.message || '提交失败，请重试');
    },
  });

  const submitCode = useMutation({
    mutationFn: async ({ roundId, language, sourceCode }: { roundId: string; language: string; sourceCode: string }) => {
      setPhase('streaming');
      setStage('received');
      setError(null);
      return mockApi.submitCode(sessionId, roundId, language, sourceCode, setStage);
    },
    onSuccess: (result) => {
      setPhase('idle');
      setStage(null);
      refresh();
      return result;
    },
    onError: (err: Error) => {
      setPhase('error');
      setError(err.message || '代码提交失败，请重试');
    },
  });

  const runSample = useMutation({
    mutationFn: ({ roundId, language, sourceCode }: { roundId: string; language: string; sourceCode: string }) =>
      mockApi.runCode(sessionId, roundId, language, sourceCode),
  });

  return {
    phase,
    stage,
    error,
    stageText: stage ? STAGE_TEXT[stage] : null,
    submitAnswer,
    submitCode,
    runSample,
  };
}
