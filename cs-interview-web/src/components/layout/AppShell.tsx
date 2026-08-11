import {
  Bell,
  BriefcaseBusiness,
  FileText,
  History,
  LayoutDashboard,
  Moon,
  PlayCircle,
  RefreshCcw,
  Sun,
  UserRound,
} from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router';
import { cn } from '@/lib/cn';
import { useJobs } from '@/hooks/use-cs-query';
import { useTheme } from '@/hooks/use-theme';
import { resetDb } from '@/lib/mock/db';
import { useToast } from '@/components/ui/feedback';

const NAV_ITEMS = [
  { to: '/', label: '面试概览', icon: LayoutDashboard, end: true },
  { to: '/resumes', label: '简历中心', icon: FileText },
  { to: '/jobs', label: 'JD 中心', icon: BriefcaseBusiness },
  { to: '/configure', label: '新建面试', icon: PlayCircle },
  { to: '/records', label: '面试记录', icon: History },
];

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-7 items-center justify-center rounded bg-accent">
        <svg viewBox="0 0 32 32" className="size-4" aria-hidden="true">
          <circle cx="11" cy="16" r="3.2" fill="currentColor" />
          <circle cx="21" cy="16" r="3.2" fill="currentColor" />
        </svg>
      </span>
      <div className="leading-none">
        <div className="text-sm font-semibold tracking-tight">CS Interview Agent</div>
        <div className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-tertiary">
          mock interview
        </div>
      </div>
    </div>
  );
}

function TargetRoleChip() {
  const { data: jobs = [] } = useJobs();
  const latest = jobs[0];
  return (
    <div className="hidden items-center gap-2 rounded border border-line bg-surface px-2.5 py-1 md:flex">
      <span className="size-1.5 rounded-full bg-accent" />
      <span className="font-mono text-[11px] text-ink-secondary">
        {latest?.name ?? '未设置目标岗位'}
      </span>
    </div>
  );
}

function ThemeToggle() {
  const { isDark, toggle } = useTheme();
  return (
    <button
      type="button"
      aria-label={isDark ? '切换到浅色主题' : '切换到深色主题'}
      title={isDark ? '切换到浅色主题' : '切换到深色主题'}
      onClick={toggle}
      className="flex size-8 items-center justify-center rounded text-ink-secondary transition-colors hover:bg-hover hover:text-ink"
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

function NotificationMenu() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        aria-label="通知"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="relative flex size-8 items-center justify-center rounded text-ink-secondary transition-colors hover:bg-hover hover:text-ink"
      >
        <Bell className="size-4" />
        <span className="absolute right-2 top-2 size-1.5 rounded-full bg-accent" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="panel-surface absolute right-0 z-40 mt-1.5 w-72 p-1.5 shadow-float">
            <div className="micro-label px-2.5 pb-2 pt-1.5">通知</div>
            <div className="flex items-start gap-2.5 rounded px-2.5 py-2.5">
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-ok" />
              <div className="min-w-0">
                <div className="text-sm">面试报告已生成</div>
                <div className="mt-0.5 text-xs text-ink-secondary">2026-08-09 · 查看能力差距与训练建议</div>
              </div>
            </div>
            <div className="flex items-start gap-2.5 rounded px-2.5 py-2.5">
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-warn" />
              <div className="min-w-0">
                <div className="text-sm">简历声明待核验</div>
                <div className="mt-0.5 text-xs text-ink-secondary">「Kafka 消费者稳定性治理」存在矛盾</div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function UserMenu() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();
  const handleReset = () => {
    resetDb();
    window.location.reload();
  };
  return (
    <div className="relative">
      <button
        type="button"
        aria-label="用户菜单"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex size-8 items-center justify-center rounded text-ink-secondary transition-colors hover:bg-hover hover:text-ink"
      >
        <UserRound className="size-4" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="panel-surface absolute right-0 z-40 mt-1.5 w-56 p-1.5 shadow-float">
            <div className="border-b border-line px-2.5 pb-2.5 pt-1.5">
              <div className="text-sm font-medium">张三</div>
              <div className="mt-0.5 font-mono text-[11px] text-ink-tertiary">Go 后端 · 校招</div>
            </div>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                navigate('/configure');
              }}
              className="mt-1 flex w-full items-center gap-2 rounded px-2.5 py-2 text-left text-sm text-ink-secondary hover:bg-hover hover:text-ink"
            >
              <PlayCircle className="size-3.5" />
              新建一场面试
            </button>
            <button
              type="button"
              onClick={handleReset}
              className="flex w-full items-center gap-2 rounded px-2.5 py-2 text-left text-sm text-ink-secondary hover:bg-hover hover:text-ink"
            >
              <RefreshCcw className="size-3.5" />
              重置演示数据
            </button>
            <div className="mt-1 border-t border-line px-2.5 pb-1 pt-2 text-xs text-ink-tertiary">
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  toast('info', '演示环境', '当前为本地演示环境，数据仅保存在本机浏览器中。');
                }}
                className="w-full text-left hover:text-ink-secondary"
              >
                退出登录
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function AppShell() {
  return (
    <div className="flex h-full flex-col bg-app">
      <header className="flex h-13 items-center gap-3 border-b border-line bg-content px-4 lg:px-6" style={{ height: 52 }}>
        <Brand />
        <div className="ml-auto flex items-center gap-1.5">
          <TargetRoleChip />
          <NotificationMenu />
          <ThemeToggle />
          <UserMenu />
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-52 shrink-0 border-r border-line bg-content lg:block">
          <nav className="sticky top-0 flex flex-col gap-0.5 p-3">
            {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    'group flex items-center gap-2.5 rounded px-3 py-2 text-sm text-ink-secondary transition-colors',
                    'hover:bg-hover hover:text-ink focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                    isActive && 'bg-hover font-medium text-ink ring-1 ring-line-strong',
                  )
                }
              >
                <Icon className="size-4 shrink-0" />
                {label}
              </NavLink>
            ))}
            <div className="mt-8 border-t border-line pt-4">
              <div className="px-3 font-mono text-[10px] uppercase leading-5 tracking-[0.14em] text-ink-tertiary">
                训练闭环
              </div>
              <p className="mt-1.5 px-3 text-xs leading-5 text-ink-tertiary">
                简历声明 → JD 要求 → 当前问题 → 回答证据 → 能力结论
              </p>
            </div>
          </nav>
        </aside>
        <main className="thin-scroll min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1160px] px-4 py-6 lg:px-8">
            {/* 移动端：横向导航 */}
            <nav className="mb-5 flex gap-1 overflow-x-auto pb-1 lg:hidden" aria-label="业务导航">
              {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cn(
                      'flex shrink-0 items-center gap-1.5 rounded border border-line bg-surface px-3 py-1.5 text-xs text-ink-secondary',
                      isActive && 'border-accent/40 bg-accent-dim text-ink',
                    )
                  }
                >
                  <Icon className="size-3.5" />
                  {label}
                </NavLink>
              ))}
            </nav>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
