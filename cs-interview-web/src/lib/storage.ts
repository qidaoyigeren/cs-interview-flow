/** 简单的 localStorage 封装：用于表单草稿等轻量持久化。 */

export function readStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeStorage<T>(key: string, value: T): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // localStorage 不可用时静默忽略（草稿丢失可接受）
  }
}

export function clearStorage(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // ignore
  }
}

/** 防抖写草稿。 */
export function makeDraftSaver<T>(key: string, debounceMs = 500) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: T | null = null;
  return {
    save(value: T) {
      pending = value;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        if (pending) writeStorage(key, pending);
      }, debounceMs);
    },
    flush() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (pending) {
        writeStorage(key, pending);
        pending = null;
      }
    },
    clear() {
      this.flush();
      clearStorage(key);
    },
  };
}
