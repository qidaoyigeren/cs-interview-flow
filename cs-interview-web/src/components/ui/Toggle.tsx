import { cn } from '@/lib/cn';

export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      disabled={disabled}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        checked ? 'bg-accent' : 'border border-line-strong bg-surface',
        disabled && 'cursor-not-allowed opacity-50',
      )}
    >
      <span
        className={cn(
          'size-3.5 rounded-full transition-transform',
          checked ? 'translate-x-[18px] bg-ink-inverse' : 'translate-x-0.5 bg-ink-tertiary',
        )}
      />
    </button>
  );
}
