import { ChevronDown } from 'lucide-react';
import {
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';
import { cn } from '@/lib/cn';

const controlBase =
  'w-full rounded border border-line bg-surface px-3 text-sm text-ink placeholder:text-ink-tertiary transition-colors hover:border-line-strong focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-50';

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(controlBase, 'h-9', className)} {...rest} />;
}

export function Textarea({
  className,
  rows = 5,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(controlBase, 'py-2 leading-6', className)} rows={rows} {...rest} />;
}

export function Select({
  className,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className={cn('relative', className)}>
      <select
        className={cn(
          controlBase,
          'h-9 appearance-none pr-8 [&>option]:bg-surface [&>option]:text-ink',
        )}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-secondary" />
    </div>
  );
}

export function Label({
  children,
  mono,
  className,
  htmlFor,
}: {
  children: ReactNode;
  mono?: boolean;
  className?: string;
  htmlFor?: string;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className={cn(
        'mb-1.5 block text-xs font-medium text-ink-secondary',
        mono && 'micro-label font-normal text-ink-tertiary',
        className,
      )}
    >
      {children}
    </label>
  );
}

export function Field({
  label,
  mono,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  mono?: boolean;
  hint?: string;
  error?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div>
      <Label mono={mono} htmlFor={htmlFor}>
        {label}
      </Label>
      {children}
      {error ? (
        <p className="mt-1.5 text-xs text-err">{error}</p>
      ) : hint ? (
        <p className="mt-1.5 text-xs text-ink-tertiary">{hint}</p>
      ) : null}
    </div>
  );
}
