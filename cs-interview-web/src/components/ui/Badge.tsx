import { cn } from '@/lib/cn';
import { type ReactNode } from 'react';

export type BadgeTone = 'neutral' | 'accent' | 'ok' | 'warn' | 'err';

const toneMap: Record<BadgeTone, { wrap: string; dot: string }> = {
  neutral: { wrap: 'border-line-strong text-ink-secondary', dot: 'bg-ink-tertiary' },
  accent: { wrap: 'border-accent/40 text-accent bg-accent-dim', dot: 'bg-accent' },
  ok: { wrap: 'border-ok/40 text-ok bg-ok-dim', dot: 'bg-ok' },
  warn: { wrap: 'border-warn/40 text-warn bg-warn-dim', dot: 'bg-warn' },
  err: { wrap: 'border-err/40 text-err bg-err-dim', dot: 'bg-err' },
};

export function Badge({
  tone = 'neutral',
  dot,
  children,
  className,
}: {
  tone?: BadgeTone;
  dot?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const palette = toneMap[tone];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-[11px] leading-5 whitespace-nowrap',
        palette.wrap,
        className,
      )}
    >
      {dot && <span className={cn('size-1.5 rounded-full', palette.dot)} />}
      {children}
    </span>
  );
}

/** 技术标签：mono 字体的小方块。 */
export function Tag({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] leading-5 text-ink-secondary',
        className,
      )}
    >
      {children}
    </span>
  );
}
