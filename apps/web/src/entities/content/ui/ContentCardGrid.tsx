import type { ReactNode, Ref } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";

import type { GridAspect } from "../model/cardLayout";
import { toGridColumns } from "./cardLayoutClass";

export type ContentCardGridProps = {
  thumbnailAspect: GridAspect;
  className?: string;
  ref?: Ref<HTMLDivElement>;
  tabIndex?: number;
  children: ReactNode;
};

/** 홈/즐겨찾기/프로필/`/my` 4곳(+ 스켈레톤 4곳)이 공유하는 그리드. 열 수는
 * 타입별로 갈린다 — `toGridColumns`가 그 규칙 하나를 쥔다.
 *
 * 열 수는 그리드가 받는 폭으로 정한다(컨테이너 쿼리, 이유는 `toGridColumns` 쪽 주석). 그리드는 자기 폭을 질의할 수
 * 없어서 바깥에 `@container` 래퍼를 하나 둔다. 이 래퍼는 내용으로 폭을 정하지 않으므로(inline-size containment)
 * 내용 폭으로 줄어드는 자리에 놓이면 폭이 0 으로 무너진다. 부모가 자식을 줄이는 경우(`items-center` 인 flex 열 등)는
 * `w-full` 이 막지만, 부모 자신의 폭이 내용으로 정해지는 경우(`w-fit`, flex 열 안에서 `mx-auto` 만 단 아이템)는
 * 막지 못한다 — 부모 폭이 바깥에서 정해지는 자리에 둔다.
 *
 * `ref`·`tabIndex`·`className`은 래퍼가 아니라 안쪽 그리드로 보낸다 — `/my`·프로필 그리드가 "더 보기"가 마지막
 * 페이지에서 사라질 때 그리드를 포커스 받는 자리로 쓴다. 앞의 둘(`ref`·`tabIndex`)을 래퍼가 삼키면 그 동작이 깨지고,
 * `className`은 포커스를 받는 요소에 붙어야 할 클래스(예: `outline-none`)를 싣는 자리라 같은 요소로 간다. */
export function ContentCardGrid({ thumbnailAspect, className, ref, tabIndex, children }: ContentCardGridProps) {
  return (
    <div className="@container w-full">
      <div ref={ref} tabIndex={tabIndex} className={cn("grid gap-3", toGridColumns(thumbnailAspect), className)}>
        {children}
      </div>
    </div>
  );
}
