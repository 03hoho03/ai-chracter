import type { ReactNode, Ref } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";

import { toGridColumns, type GridAspect } from "../model/cardLayout";

export type ContentCardGridProps = {
  thumbnailAspect: GridAspect;
  className?: string;
  ref?: Ref<HTMLDivElement>;
  tabIndex?: number;
  children: ReactNode;
};

/** card-grid-techspec.md T-4 — 홈/즐겨찾기/프로필/`/my` 4곳(+ 스켈레톤 4곳)이 공유하는 그리드. 열 수는
 * 타입별로 갈린다(D-5) — `toGridColumns`가 그 규칙 하나를 쥔다.
 *
 * `ref`·`tabIndex`를 통과시킨다 — `/my`·프로필 그리드가 "더 보기"가 마지막 페이지에서 사라질 때 포커스를
 * 받는 자리로 쓴다(A-2). 이 컴포넌트가 그 둘을 삼키면 그 동작이 깨진다. */
export function ContentCardGrid({ thumbnailAspect, className, ref, tabIndex, children }: ContentCardGridProps) {
  return (
    <div ref={ref} tabIndex={tabIndex} className={cn("grid gap-3", toGridColumns(thumbnailAspect), className)}>
      {children}
    </div>
  );
}
