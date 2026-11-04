import type { ReactNode } from "react";

import { Kbd } from "@/shared/ui/Kbd";

type KeyHintProps = {
  keys: ReadonlyArray<string>;
  children: ReactNode;
};

/** 상태 줄의 단축키 힌트 한 칸 — 키 낱자들 뒤에 하는 일. */
export function KeyHint({ keys, children }: KeyHintProps) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1">
      {keys.map((key) => (
        <Kbd key={key}>{key}</Kbd>
      ))}
      <span className="ml-0.5">{children}</span>
    </span>
  );
}
