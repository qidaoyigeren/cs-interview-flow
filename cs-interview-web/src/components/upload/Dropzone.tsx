import { FileUp } from 'lucide-react';
import { useRef, useState, type DragEvent } from 'react';
import { cn } from '@/lib/cn';
import { Spinner } from '@/components/ui/feedback';

export function Dropzone({
  accept,
  acceptHint,
  busy,
  busyLabel,
  onFiles,
  className,
}: {
  accept: string[];
  acceptHint?: string;
  busy?: boolean;
  busyLabel?: string;
  onFiles: (file: File) => void;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) onFiles(file);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="点击或拖拽上传文件"
      onClick={() => inputRef.current?.click()}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click();
      }}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={cn(
        'flex cursor-pointer flex-col items-center justify-center rounded border border-dashed border-line-strong px-6 py-8 text-center transition-colors',
        'hover:border-accent hover:bg-accent-dim/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        dragging && 'border-accent bg-accent-dim',
        className,
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept.join(',')}
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFiles(file);
          event.target.value = '';
        }}
      />
      {busy ? (
        <Spinner className="size-5" />
      ) : (
        <FileUp className="mb-2 size-5 text-ink-secondary" />
      )}
      <div className="text-sm font-medium text-ink-secondary">
        {busy ? busyLabel ?? '上传中…' : '点击选择或拖拽文件到此处'}
      </div>
      <div className="mt-1 font-mono text-[11px] text-ink-tertiary">
        {acceptHint ?? accept.join(' / ')}
      </div>
    </div>
  );
}

export function validateUpload(file: File, accept: string[]): string | null {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  const okExt = accept.some((type) => ext === type.toLowerCase());
  const okMime = accept.some((type) => file.type.toLowerCase().includes(type.toLowerCase()));
  if (!okExt && !okMime) {
    return `不支持的文件类型“${ext || '未知'}”，请上传 ${accept.join(' / ')} 格式。`;
  }
  return null;
}
