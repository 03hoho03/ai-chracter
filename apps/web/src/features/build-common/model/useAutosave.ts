import { useEffect, useMemo } from "react";

function debounce<TArgs extends unknown[]>(fn: (...args: TArgs) => void, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const debounced = (...args: TArgs) => {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  debounced.cancel = () => {
    if (timer !== undefined) clearTimeout(timer);
  };
  return debounced;
}

/** techspec-builder-common.md §1 — 캐릭터/스토리 빌더 공용 자동저장 훅.
 * 필드 변경(subscribe) 시 디바운스 PATCH, "임시저장" 클릭 시 saveNow로 즉시 PATCH. */
export function useAutosave<TForm, TPayload>(opts: {
  subscribe: (cb: (values: TForm) => void) => () => void;
  formToServer: (values: TForm) => TPayload;
  save: (payload: TPayload) => Promise<void>;
  debounceMs?: number;
}) {
  const debouncedSave = useMemo(
    () => debounce((values: TForm) => opts.save(opts.formToServer(values)), opts.debounceMs ?? 1500),
    [opts.save, opts.formToServer, opts.debounceMs],
  );

  useEffect(() => opts.subscribe(debouncedSave), [opts, debouncedSave]);

  return {
    saveNow: (values: TForm) => {
      debouncedSave.cancel();
      opts.save(opts.formToServer(values));
    },
  };
}
