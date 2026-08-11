import { Button } from '@/components/ui/Button';

export function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center text-center">
      <div className="font-mono text-5xl font-semibold text-ink-tertiary">404</div>
      <h1 className="mt-4 text-lg font-semibold">页面不存在</h1>
      <p className="mt-2 max-w-sm text-sm leading-6 text-ink-secondary">
        你访问的页面不存在或已被移动。可以从面试概览重新开始。
      </p>
      <Button variant="primary" to="/" className="mt-6">
        返回面试概览
      </Button>
    </div>
  );
}
