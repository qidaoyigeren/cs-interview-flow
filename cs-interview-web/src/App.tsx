import { RouterProvider, createBrowserRouter } from 'react-router';
import { ToastProvider } from '@/components/ui/feedback';
import { AppShell } from '@/components/layout/AppShell';
import { Configure } from '@/pages/Configure';
import { JobDetail } from '@/pages/JobDetail';
import { Jobs } from '@/pages/Jobs';
import { NotFound } from '@/pages/NotFound';
import { Onboarding } from '@/pages/Onboarding';
import { Overview } from '@/pages/Overview';
import { Records } from '@/pages/Records';
import { Report } from '@/pages/Report';
import { ResumeDetail } from '@/pages/ResumeDetail';
import { Resumes } from '@/pages/Resumes';
import { Session } from '@/pages/Session';

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'resumes', element: <Resumes /> },
      { path: 'resumes/:id', element: <ResumeDetail /> },
      { path: 'jobs', element: <Jobs /> },
      { path: 'jobs/:id', element: <JobDetail /> },
      { path: 'configure', element: <Configure /> },
      { path: 'session/:id', element: <Session /> },
      { path: 'report/:id', element: <Report /> },
      { path: 'records', element: <Records /> },
      { path: 'onboarding', element: <Onboarding /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export function App() {
  return (
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>
  );
}
