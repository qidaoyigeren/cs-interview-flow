import { Fragment } from 'react';
import { cn } from '@/lib/cn';
import type { EvidenceNode, EvidenceState } from '@/lib/types';

const stateDot: Record<EvidenceState, string> = {
  pending: 'border border-line-strong bg-surface',
  verifying: 'bg-accent ring-2 ring-accent/30 pulse-dot',
  proven: 'bg-ok',
  insufficient: 'bg-warn',
  contradicted: 'bg-err',
};

const stateText: Record<EvidenceState, string> = {
  pending: 'text-ink-tertiary',
  verifying: 'text-accent',
  proven: 'text-ok',
  insufficient: 'text-warn',
  contradicted: 'text-err',
};

export function EvidenceTrack({
  nodes,
  streaming,
  streamingText,
  className,
  compact,
}: {
  nodes: EvidenceNode[];
  streaming?: boolean;
  streamingText?: string | null;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div className={cn('w-full', className)}>
      <div className="relative flex items-start">
        {nodes.map((node, index) => (
          <Fragment key={node.key}>
            {index > 0 && (
              <div
                className={cn(
                  'mt-[7px] shrink-0',
                  node.state === 'verifying' ? 'bg-accent' : 'bg-line-strong',
                )}
                style={{ width: compact ? 12 : 20, height: 2 }}
              />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex h-4 items-center justify-center">
                <span
                  className={cn('size-2 shrink-0 rounded-full transition-colors', stateDot[node.state])}
                  aria-hidden="true"
                />
              </div>
              <div
                className={cn(
                  'mt-1 truncate text-center font-mono leading-4',
                  compact ? 'text-[9px]' : 'text-[10px]',
                  stateText[node.state],
                )}
                title={node.label}
              >
                {node.label}
              </div>
              {node.hint && (
                <div className="mt-0.5 truncate text-center text-[10px] text-ink-tertiary" title={node.hint}>
                  {node.hint}
                </div>
              )}
            </div>
          </Fragment>
        ))}
        {streaming && (
          <div className="pointer-events-none absolute inset-x-0 top-[7px] h-px overflow-hidden" aria-hidden="true">
            <div className="track-scan h-full w-1/4 bg-accent" />
          </div>
        )}
      </div>
      {streaming && streamingText && (
        <div className="mt-2 flex items-center justify-center gap-1.5">
          <span className="size-1.5 rounded-full bg-accent pulse-dot" />
          <span className="font-mono text-[11px] text-accent">{streamingText}</span>
        </div>
      )}
    </div>
  );
}

/** 证据状态的中文标签。 */
export const EVIDENCE_STATE_LABEL: Record<EvidenceState, string> = {
  pending: '待验证',
  verifying: '正在验证',
  proven: '已证明',
  insufficient: '证据不足',
  contradicted: '存在矛盾',
};
