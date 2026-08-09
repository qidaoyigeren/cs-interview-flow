import { useInterviewAdminSessions } from '@/hooks/use-cs-interview-request';
import { InterviewShell, PageHeading, StatusPill } from '@/pages/cs-interview/components';
import { Routes } from '@/routes';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

export default function AdminSessions() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const { data, isPending, error } = useInterviewAdminSessions(page, status);

  const statuses = ['', 'created', 'awaiting_answer', 'evaluating', 'completed', 'failed', 'aborted'];

  if (error) {
    return (
      <InterviewShell>
        <div className="p-8 text-state-error">
          {t('csInterview.admin.unauthorized', { defaultValue: 'Administrator access required.' })}
        </div>
      </InterviewShell>
    );
  }

  return (
    <InterviewShell>
      <PageHeading
        eyebrow="ops console"
        title={t('csInterview.admin.sessionsTitle', { defaultValue: 'Session audit' })}
        description={t('csInterview.admin.sessionsDescription', {
          defaultValue: 'Audit session timelines, planner decisions and replay determinism.',
        })}
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {statuses.map((value) => (
          <button
            key={value || 'all'}
            type="button"
            onClick={() => {
              setPage(1);
              setStatus(value);
            }}
            className={`rounded-full border px-3 py-1 text-xs ${
              status === value
                ? 'border-accent-primary bg-accent-primary-5 text-text-primary'
                : 'border-border-button text-text-secondary hover:text-text-primary'
            }`}
          >
            {value === '' ? 'all' : value}
          </button>
        ))}
      </div>
      {isPending && <div className="p-8 text-text-secondary">Loading…</div>}
      <div className="overflow-x-auto rounded-lg border border-border-button">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="bg-bg-card text-xs uppercase tracking-wide text-text-secondary">
            <tr>
              <th className="px-4 py-3">ID</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Planner</th>
              <th className="px-4 py-3">Prompt</th>
              <th className="px-4 py-3">Questions</th>
              <th className="px-4 py-3">Failure</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((session) => (
              <tr key={session.id} className="border-t border-border-button">
                <td className="px-4 py-3">
                  <Link
                    to={`${Routes.CsInterviewAdminSessionDetail}/${session.id}`}
                    className="font-mono text-accent-primary hover:underline"
                  >
                    {session.id}
                  </Link>
                </td>
                <td className="px-4 py-3">
                  <StatusPill status={session.status} />
                </td>
                <td className="px-4 py-3 font-mono text-xs">{session.plannerVersion}</td>
                <td className="px-4 py-3 font-mono text-xs">{session.promptVersion}</td>
                <td className="px-4 py-3">{session.completedQuestionCount}</td>
                <td className="px-4 py-3 text-state-error">{session.failureCode ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex items-center gap-3 text-sm">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => setPage((value) => Math.max(1, value - 1))}
          className="rounded-md border border-border-button px-3 py-1 disabled:opacity-40"
        >
          Prev
        </button>
        <span className="font-mono text-xs">page {page}</span>
        <button
          type="button"
          onClick={() => setPage((value) => value + 1)}
          className="rounded-md border border-border-button px-3 py-1"
        >
          Next
        </button>
      </div>
    </InterviewShell>
  );
}
