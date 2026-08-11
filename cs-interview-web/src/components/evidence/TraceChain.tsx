import { ChevronRight } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import type { EvidenceState } from '@/lib/types';
import { EVIDENCE_STATE_LABEL } from './EvidenceTrack';

export interface TraceLink {
  label: string;
  state: EvidenceState;
  detail?: ReactNode;
  stateLabel?: string;
}

const stateDot: Record<EvidenceState, string> = {
  pending: 'border border-line-strong bg-surface',
  verifying: 'bg-accent ring-2 ring-accent/30',
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

/** 垂直证据溯源链路：简历声明 → JD 要求 → 考题 → 回答证据 → 能力结论，逐级可展开。 */
export function TraceChain({ links, defaultOpen = false }: { links: TraceLink[]; defaultOpen?: boolean }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  return (
    <ol className="relative">
      {links.map((link, index) => {
        const expanded = open[index] ?? defaultOpen;
        const hasDetail = link.detail != null;
        return (
          <li key={index} className="relative flex gap-3 pb-4 last:pb-0">
            {index < links.length - 1 && (
              <span className="absolute left-[5px] top-4 h-full w-px bg-line" aria-hidden="true" />
            )}
            <span className={cn('relative z-10 mt-1 size-2.5 shrink-0 rounded-full', stateDot[link.state])} />
            <div className="min-w-0 flex-1">
              <button
                type="button"
                disabled={!hasDetail}
                onClick={() => hasDetail && setOpen((prev) => ({ ...prev, [index]: !expanded }))}
                className={cn(
                  'flex w-full items-center justify-between gap-2 rounded text-left text-sm',
                  hasDetail ? 'cursor-pointer hover:bg-hover' : 'cursor-default',
                )}
              >
                <span className="flex items-center gap-2">
                  <span className="text-ink">{link.label}</span>
                  <span className={cn('font-mono text-[10px]', stateText[link.state])}>
                    {link.stateLabel ?? EVIDENCE_STATE_LABEL[link.state]}
                  </span>
                </span>
                {hasDetail && (
                  <ChevronRight
                    className={cn('size-3.5 shrink-0 text-ink-tertiary transition-transform', expanded && 'rotate-90')}
                  />
                )}
              </button>
              {hasDetail && expanded && (
                <div className="mt-2 rounded border border-line bg-surface px-3 py-2.5 text-sm leading-6 text-ink-secondary">
                  {link.detail}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
