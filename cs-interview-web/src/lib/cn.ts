export type ClassValue = string | number | null | undefined | false;

/** 轻量 className 合并工具，避免额外依赖。 */
export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(' ');
}
