import { cn } from '@/lib/cn';
import { type ReactNode } from 'react';

export function Panel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={cn('panel', className)}>{children}</section>;
}

export function PanelHeader({
  title,
  eyebrow,
  action,
  className,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        'flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3',
        className,
      )}
    >
      <div>
        {eyebrow && <div className="micro-label mb-1">{eyebrow}</div>}
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      {action}
    </header>
  );
}

export function PanelBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn('p-4', className)}>{children}</div>;
}
