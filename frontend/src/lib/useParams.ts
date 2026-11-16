import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/** Filter state lives in the URL, so a filtered view can be shared or reloaded. */
export function useUrlState() {
  const [params, setParams] = useSearchParams();

  const set = useCallback(
    (patch: Record<string, string | string[] | null | undefined>, resetPage = true) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            next.delete(k);
            if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
            else if (v) next.set(k, v);
          }
          if (resetPage && !("page" in patch)) next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  return { params, set };
}

export const PAGE_SIZE = 50;

export function sinceFromWindow(window: string | null): string | undefined {
  const hours = { "1h": 1, "24h": 24, "7d": 168 }[window ?? ""];
  return hours ? new Date(Date.now() - hours * 3_600_000).toISOString() : undefined;
}
