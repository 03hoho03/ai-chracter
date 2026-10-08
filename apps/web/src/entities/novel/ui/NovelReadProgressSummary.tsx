import type { ReactNode } from "react";

import type { NovelReadProgress } from "../model/novelReadProgress";

/** 목차 머리 — 제목과 같은 줄 오른쪽의 "M/N화 읽음", 그 아래 얇은 진행 막대. 수치는 글자가 지고 막대는 그림이라
 * `aria-hidden` 이다. 막대는 위치 표시라 길이 변화에 전환을 두지 않는다. 채움은 무채색 `foreground` 다 — 읽음은
 * 상태라 강조색을 쓰지 않는다(DESIGN.md One-Accent 규칙). 트랙은 `secondary` 라 페이지·시트 두 표면 모두에서 보인다. */
export function NovelReadProgressSummary({
  heading,
  progress,
  labelId,
}: {
  /** 왼쪽에 놓을 목차 제목(페이지는 `h2`, 시트는 시트 제목). */
  heading: ReactNode;
  progress: NovelReadProgress;
  labelId?: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        {heading}
        <p id={labelId} className="shrink-0 text-sm text-muted-foreground tabular-nums">
          {progress.finishedCount}/{progress.totalCount}화 읽음
        </p>
      </div>
      <div aria-hidden className="h-1 overflow-hidden rounded-full bg-secondary">
        <div className="h-full rounded-full bg-foreground" style={{ width: `${progress.ratio * 100}%` }} />
      </div>
    </div>
  );
}
