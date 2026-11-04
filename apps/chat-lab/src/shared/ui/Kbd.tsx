import type { ReactNode } from "react";

/** 단축키 낱자 하나. 상태 줄·버튼 안에서 "이 키를 누른다"를 글자와 구분해 보인다. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-4 min-w-4 items-center justify-center rounded-sm border border-border-strong px-1 font-mono text-label leading-none text-ink-secondary">
      {children}
    </kbd>
  );
}
