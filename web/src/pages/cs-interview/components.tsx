import { cn } from '@/lib/utils';
import { Routes } from '@/routes';
import {
  BookOpenCheck,
  BriefcaseBusiness,
  ChevronRight,
  CircleDot,
  ClipboardCheck,
  Database,
  FileText,
  Gauge,
  ListChecks,
  MessageSquareWarning,
  Radio,
  Settings2,
  ShieldCheck,
  Target,
} from 'lucide-react';
import { PropsWithChildren } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router';

const ShellLinks = [
  { to: Routes.CsInterview, key: 'home', icon: Radio },
  { to: Routes.CsInterviewConfigure, key: 'configure', icon: Settings2 },
  { to: Routes.CsInterviewKnowledge, key: 'knowledge', icon: Database },
  { to: Routes.CsInterviewResumes, key: 'resumes', icon: FileText },
  { to: Routes.CsInterviewJobs, key: 'jobs', icon: BriefcaseBusiness },
];

const AdminLinks = [
  {
    to: Routes.CsInterviewAdminQuality,
    key: 'adminQuality',
    icon: ShieldCheck,
  },
  {
    to: Routes.CsInterviewAdminSessions,
    key: 'adminSessions',
    icon: ListChecks,
  },
  {
    to: Routes.CsInterviewAdminGovernance,
    key: 'adminGovernance',
    icon: BookOpenCheck,
  },
  {
    to: Routes.CsInterviewAdminFeedback,
    key: 'adminFeedback',
    icon: MessageSquareWarning,
  },
  {
    to: Routes.CsInterviewAdminCompetencies,
    key: 'adminCompetencies',
    icon: Target,
  },
  {
    to: Routes.CsInterviewAdminCalibration,
    key: 'adminCalibration',
    icon: Gauge,
  },
  {
    to: Routes.CsInterviewAdminExperiments,
    key: 'adminExperiments',
    icon: ClipboardCheck,
  },
];

export const NativeSelectThemeClass =
  'text-text-primary [&>option]:bg-bg-base [&>option]:text-text-primary';

export function InterviewShell({ children }: PropsWithChildren) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  return (
    <div className="h-full overflow-y-auto bg-bg-base text-text-primary">
      <div className="mx-auto grid min-h-full max-w-[1440px] grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="border-b border-border-button px-5 py-4 md:border-b-0 md:border-r md:px-6 md:py-10">
          <div className="flex items-center gap-3 md:mb-12">
            <span className="relative flex size-9 items-center justify-center rounded-full border border-border-default bg-bg-card">
              <CircleDot className="size-4" />
              <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-state-error" />
            </span>
            <div>
              <div className="text-sm font-semibold">
                {t('csInterview.brand')}
              </div>
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-secondary">
                live practice
              </div>
            </div>
          </div>
          <nav className="mt-4 flex gap-2 overflow-x-auto md:mt-0 md:block md:space-y-2">
            {ShellLinks.map(({ to, key, icon: Icon }) => {
              const active = pathname === to;
              return (
                <Link
                  key={to}
                  to={to}
                  className={cn(
                    'group flex shrink-0 items-center gap-3 rounded-md px-3 py-2.5 text-sm text-text-secondary transition-colors',
                    'hover:bg-bg-card hover:text-text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary',
                    active && 'bg-bg-card font-medium text-text-primary',
                  )}
                >
                  <Icon className="size-4" />
                  <span>{t(`csInterview.nav.${key}`)}</span>
                  <ChevronRight className="ml-auto hidden size-3 opacity-0 transition-opacity group-hover:opacity-100 md:block" />
                </Link>
              );
            })}
            {AdminLinks.map(({ to, key, icon: Icon }) => {
              const active = pathname === to || pathname.startsWith(`${to}/`);
              return (
                <Link
                  key={to}
                  to={to}
                  className={cn(
                    'group flex shrink-0 items-center gap-3 rounded-md px-3 py-2.5 text-sm text-text-secondary transition-colors',
                    'hover:bg-bg-card hover:text-text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary',
                    active && 'bg-bg-card font-medium text-text-primary',
                  )}
                >
                  <Icon className="size-4" />
                  <span>{t(`csInterview.nav.${key}`)}</span>
                  <ChevronRight className="ml-auto hidden size-3 opacity-0 transition-opacity group-hover:opacity-100 md:block" />
                </Link>
              );
            })}
          </nav>
          <div className="mt-12 hidden border-t border-border-button pt-5 text-xs leading-5 text-text-secondary md:block">
            {t('csInterview.privacyNote')}
          </div>
        </aside>
        <main className="min-w-0 px-5 py-8 sm:px-8 md:px-12 md:py-12 lg:px-16">
          {children}
        </main>
      </div>
    </div>
  );
}

export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="mb-10 flex flex-col gap-5 border-b border-border-button pb-8 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-3xl">
        <div className="mb-3 font-mono text-[11px] uppercase tracking-[0.16em] text-text-secondary">
          {eyebrow}
        </div>
        <h1 className="text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">
          {title}
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-text-secondary">
          {description}
        </p>
      </div>
      {action}
    </header>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="border border-dashed border-border-default px-6 py-12 text-center">
      <BookOpenCheck className="mx-auto mb-4 size-7 text-text-secondary" />
      <h2 className="font-medium">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-text-secondary">
        {description}
      </p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const { t } = useTranslation();
  const complete = status === 'completed';
  const active = [
    'created',
    'preparing_question',
    'awaiting_answer',
    'evaluating',
  ].includes(status);
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wide',
        complete &&
          'border-state-success bg-state-success-5 text-state-success',
        active && 'border-accent-primary bg-accent-primary-5 text-text-primary',
        !complete && !active && 'border-border-button text-text-secondary',
      )}
    >
      <span
        className={cn(
          'size-1.5 rounded-full bg-text-secondary',
          complete && 'bg-state-success',
          active && 'bg-accent-primary',
        )}
      />
      {t(`csInterview.status.${status}`, { defaultValue: status })}
    </span>
  );
}

export function ScoreMark({
  value,
  total = 4,
}: {
  value: number;
  total?: number;
}) {
  return (
    <div className="inline-flex items-baseline gap-1 font-mono">
      <span className="text-3xl font-semibold tracking-[-0.05em]">
        {value.toFixed(2)}
      </span>
      <span className="text-xs text-text-secondary">/ {total}</span>
    </div>
  );
}

export function SectionTitle({
  icon: Icon = ClipboardCheck,
  children,
}: PropsWithChildren<{ icon?: React.ComponentType<{ className?: string }> }>) {
  return (
    <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
      <Icon className="size-4 text-text-secondary" />
      {children}
    </h2>
  );
}
