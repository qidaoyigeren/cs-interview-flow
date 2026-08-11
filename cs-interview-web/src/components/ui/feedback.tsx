import { AlertCircle, CheckCircle2, Info, Loader2, TriangleAlert, X } from 'lucide-react';
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { cn } from '@/lib/cn';
import { Button } from './Button';

/* ---------------- Spinner / Loading ---------------- */

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('animate-spin text-ink-secondary', className)} />;
}

export function Loading({
  label = '加载中…',
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div className={cn('flex items-center justify-center gap-2 py-12 text-sm text-ink-secondary', className)}>
      <Spinner className="size-4" />
      <span>{label}</span>
    </div>
  );
}

/* ---------------- EmptyState ---------------- */

export function EmptyState({
  icon: Icon = Info,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col items-center border border-dashed border-line px-6 py-12 text-center', className)}>
      <Icon className="mb-3 size-7 text-ink-tertiary" />
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-1.5 max-w-md text-sm leading-6 text-ink-secondary">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* ---------------- Toast ---------------- */

export type ToastKind = 'success' | 'error' | 'info' | 'warning';

interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
}

interface ToastContextValue {
  toast: (kind: ToastKind, title: string, detail?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const toastIcon: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 className="size-4 text-ok" />,
  error: <AlertCircle className="size-4 text-err" />,
  warning: <TriangleAlert className="size-4 text-warn" />,
  info: <Info className="size-4 text-accent" />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(
    (kind: ToastKind, title: string, detail?: string) => {
      counter.current += 1;
      const id = counter.current;
      setItems((prev) => [...prev.slice(-3), { id, kind, title, detail }]);
      window.setTimeout(() => dismiss(id), detail ? 6000 : 4000);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className="pointer-events-auto panel-surface flex items-start gap-3 px-3.5 py-3 shadow-float"
          >
            <span className="mt-0.5 shrink-0">{toastIcon[item.kind]}</span>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">{item.title}</div>
              {item.detail && (
                <div className="mt-1 text-xs leading-5 text-ink-secondary">{item.detail}</div>
              )}
            </div>
            <button
              type="button"
              aria-label="关闭提示"
              onClick={() => dismiss(item.id)}
              className="shrink-0 rounded p-0.5 text-ink-tertiary hover:text-ink"
            >
              <X className="size-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error('useToast 必须在 ToastProvider 内使用');
  return value;
}

/* ---------------- Dialog ---------------- */

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = 'max-w-md',
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-overlay" onClick={onClose} aria-hidden="true" />
      <div className={cn('panel relative w-full bg-content p-5 shadow-float', width)}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold">{title}</h3>
            {description && <p className="mt-1.5 text-sm leading-6 text-ink-secondary">{description}</p>}
          </div>
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="shrink-0 rounded p-1 text-ink-tertiary hover:bg-hover hover:text-ink"
          >
            <X className="size-4" />
          </button>
        </div>
        {children && <div className="mt-4">{children}</div>}
        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmText = '确认',
  danger,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmText?: string;
  danger?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            onClick={() => {
              onConfirm();
              onClose();
            }}
          >
            {confirmText}
          </Button>
        </>
      }
    />
  );
}
