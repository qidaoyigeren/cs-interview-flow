import { Button } from '@/components/ui/button';
import {
  useInterviewKnowledgeBootstrap,
  useInterviewSessions,
} from '@/hooks/use-cs-interview-request';
import { Routes } from '@/routes';
import dayjs from 'dayjs';
import { ArrowRight, History, Target } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import {
  EmptyState,
  InterviewShell,
  PageHeading,
  ScoreMark,
  SectionTitle,
  StatusPill,
} from './components';

export default function CsInterviewHome() {
  const { t } = useTranslation();
  useInterviewKnowledgeBootstrap();
  const { data: sessions = [], isLoading } = useInterviewSessions();
  const completed = sessions.filter((item) => item.status === 'completed');
  const average = completed.length
    ? completed.reduce(
        (sum, item) => sum + (item.report?.overallScore || 0),
        0,
      ) / completed.length
    : 0;
  return (
    <InterviewShell>
      <PageHeading
        eyebrow={t('csInterview.home.eyebrow')}
        title={t('csInterview.home.title')}
        description={t('csInterview.home.description')}
        action={
          <Button asLink to={Routes.CsInterviewConfigure} size="lg">
            {t('csInterview.home.newInterview')}
            <ArrowRight />
          </Button>
        }
      />
      <section className="mb-12 grid gap-px overflow-hidden border border-border-button bg-border-button sm:grid-cols-3">
        <div className="bg-bg-base p-6">
          <div className="mb-5 font-mono text-[10px] uppercase tracking-widest text-text-secondary">
            {t('csInterview.home.completed')}
          </div>
          <div className="text-3xl font-semibold">{completed.length}</div>
        </div>
        <div className="bg-bg-base p-6">
          <div className="mb-5 font-mono text-[10px] uppercase tracking-widest text-text-secondary">
            {t('csInterview.home.average')}
          </div>
          <ScoreMark value={average} />
        </div>
        <div className="bg-bg-base p-6">
          <div className="mb-5 font-mono text-[10px] uppercase tracking-widest text-text-secondary">
            {t('csInterview.home.nextFocus')}
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Target className="size-4" />
            {completed[0]?.report?.weaknesses?.[0]?.topic ||
              t('csInterview.home.noFocus')}
          </div>
        </div>
      </section>
      <SectionTitle icon={History}>{t('csInterview.home.recent')}</SectionTitle>
      {isLoading ? (
        <div className="h-32 animate-pulse bg-bg-card" />
      ) : sessions.length === 0 ? (
        <EmptyState
          title={t('csInterview.home.emptyTitle')}
          description={t('csInterview.home.emptyDescription')}
          action={
            <Button asLink to={Routes.CsInterviewConfigure} variant="outline">
              {t('csInterview.home.configure')}
            </Button>
          }
        />
      ) : (
        <div className="divide-y divide-border-button border-y border-border-button">
          {sessions.slice(0, 8).map((session) => (
            <Link
              key={session.id}
              to={
                session.status === 'completed'
                  ? `${Routes.CsInterviewReport}/${session.id}`
                  : `${Routes.CsInterviewSession}/${session.id}`
              }
              className="group grid gap-3 py-5 transition-colors hover:bg-bg-card sm:grid-cols-[1fr_auto_auto] sm:items-center sm:px-4"
            >
              <div>
                <div className="font-medium">
                  {t('csInterview.home.sessionLabel', {
                    number: session.currentRoundSequence || 1,
                  })}
                </div>
                <div className="mt-1 text-xs text-text-secondary">
                  {dayjs(session.createdAt).format('YYYY-MM-DD HH:mm')}
                </div>
              </div>
              <StatusPill status={session.status} />
              <div className="font-mono text-xs text-text-secondary">
                {session.completedQuestionCount}/{session.maxQuestions}
              </div>
            </Link>
          ))}
        </div>
      )}
    </InterviewShell>
  );
}
