import { cn } from '@/lib/cn';

export interface SegmentedOption<T extends string | number> {
  value: T;
  label: string;
  hint?: string;
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  className,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={cn('flex w-full gap-0.5 rounded border border-line bg-surface p-0.5', className)}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'flex-1 rounded px-2 py-1.5 text-center text-xs transition-colors',
              active ? 'bg-hover text-ink ring-1 ring-line-strong' : 'text-ink-secondary hover:text-ink',
            )}
          >
            {option.label}
            {option.hint && <span className="ml-1 font-mono text-[10px] text-ink-tertiary">{option.hint}</span>}
          </button>
        );
      })}
    </div>
  );
}
