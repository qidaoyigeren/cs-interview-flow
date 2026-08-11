import { cn } from '@/lib/cn';

export function Progress({
  value,
  max = 100,
  tone = 'accent',
  className,
}: {
  value: number;
  max?: number;
  tone?: 'accent' | 'ok' | 'warn' | 'err';
  className?: string;
}) {
  const percent = Math.max(0, Math.min(100, (value / max) * 100));
  const color = {
    accent: 'bg-accent',
    ok: 'bg-ok',
    warn: 'bg-warn',
    err: 'bg-err',
  }[tone];
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-surface', className)}
    >
      <div className={cn('h-full rounded-full transition-[width] duration-500', color)} style={{ width: `${percent}%` }} />
    </div>
  );
}
