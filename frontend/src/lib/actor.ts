import { useCallback, useState } from "react";

const KEY = "finsight.analyst";

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

/**
 * Who the console says performed an action. There is no login: this is the
 * name recorded on case events (the audit trail), not an access control.
 */
export function useAnalyst(): [string, (name: string) => void] {
  const [name, setName] = useState(read);
  const update = useCallback((next: string) => {
    const trimmed = next.trim();
    setName(trimmed);
    try {
      localStorage.setItem(KEY, trimmed);
    } catch {
      /* private mode: the name just won't persist across reloads */
    }
  }, []);
  return [name, update];
}
