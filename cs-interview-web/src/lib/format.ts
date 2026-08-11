import dayjs from 'dayjs';

/** 统一日期展示。 */
export function formatDate(value?: string): string {
  return value ? dayjs(value).format('YYYY-MM-DD') : '—';
}

/** 统一时间展示。 */
export function formatTime(value?: string): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—';
}

/** 相对时间：用于列表的紧凑展示。 */
export function formatRelative(value?: string): string {
  if (!value) return '—';
  const diff = dayjs().diff(dayjs(value), 'minute');
  if (diff < 1) return '刚刚';
  if (diff < 60) return `${diff} 分钟前`;
  const hours = Math.floor(diff / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return dayjs(value).format('MM-DD');
}

/** 分数保留一位小数（mono 数字排版）。 */
export function formatScore(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}

/** 秒数 → mm:ss / hh:mm:ss。 */
export function formatDuration(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return hours > 0
    ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`;
}

/** 能力评分（0-10）转百分比条宽度。 */
export function abilityPercent(score: number): number {
  return Math.max(2, Math.min(100, Math.round(score * 10)));
}

/** 0-100 匹配度转 0-10 能力分。 */
export function percentToAbility(percent: number): number {
  return Math.max(0, Math.min(10, Math.round(percent / 10)));
}
