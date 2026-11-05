// After a human confirms, edits or rejects a criterion the API asks the worker to
// recompute the stored verdict (DEC-033). That takes a few seconds (the API debounces
// bursts of changes), so the verdict panel follows the refresh with a short, bounded
// poll instead of a tight loop. No timers are created here: the caller passes `sleep`.

import type { VerdictV2 } from "./verdict-v2-model.ts";

/** Browser event the intent panel fires after a successful criterion change. */
export const INTENT_CHANGED_EVENT = "radius:intent-changed";

/** Waits between polls (ms): about 32 s in total, then the panel stays on what it has. */
export const REFRESH_DELAYS_MS: readonly number[] = [1500, 2500, 4000, 6000, 8000, 10000];

export type RefreshState = {
  /** The API says a recompute is queued, so the shown verdict is stale. */
  pending: boolean;
  /** The worker tried and failed at least once (still queued, retried with backoff). */
  failed: boolean;
};

export type VerdictSnapshot = { verdict: VerdictV2; refresh: RefreshState };

export function notifyIntentChanged(analysisId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(new CustomEvent(INTENT_CHANGED_EVENT, { detail: { analysisId } }));
  } catch {
    // A missing verdict panel (or an old browser) must never break the confirm.
  }
}

/** Subscribe to criterion changes of one analysis; returns the unsubscribe function. */
export function onIntentChanged(analysisId: string, handler: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<{ analysisId?: string }>).detail;
    if (detail?.analysisId === analysisId) handler();
  };
  window.addEventListener(INTENT_CHANGED_EVENT, listener);
  return () => window.removeEventListener(INTENT_CHANGED_EVENT, listener);
}

/**
 * Poll until the stored revision is above `baseline`, or the API reports that no
 * refresh is queued any more (nothing changed), or `delaysMs` is used up.
 * Returns the last snapshot that was loaded (null if every load failed).
 * `onSnapshot` receives every successful load so the UI can show progress.
 */
export async function followRefresh(options: {
  baseline: number;
  load: () => Promise<VerdictSnapshot>;
  sleep: (ms: number) => Promise<void>;
  cancelled: () => boolean;
  delaysMs?: readonly number[];
  onSnapshot?: (snapshot: VerdictSnapshot) => void;
}): Promise<VerdictSnapshot | null> {
  const delays = options.delaysMs ?? REFRESH_DELAYS_MS;
  let last: VerdictSnapshot | null = null;
  for (const delay of delays) {
    await options.sleep(delay);
    if (options.cancelled()) return last;
    try {
      last = await options.load();
    } catch {
      continue; // a transient error: try again after the next delay
    }
    if (options.cancelled()) return last;
    options.onSnapshot?.(last);
    if (last.verdict.revision > options.baseline || !last.refresh.pending) return last;
  }
  return last;
}
