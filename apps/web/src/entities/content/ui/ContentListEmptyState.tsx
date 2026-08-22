import type { ReactNode } from "react";

/** techspec-home-discovery.md §2 — 홈 검색/필터와 즐겨찾기 목록이 공용으로 쓰는 결과 0건 안내.
 *
 * `action`은 이 빈 상태에서 빠져나가는 길을 패널 **안**에 두기 위한 슬롯이다(`/my`의 `필터 해제`,
 * 이후 US-011의 `작품 만들기`). 문구만으로는 "아직 만든 작품이 없어요"(만들라)와 "조건에 맞는 작품이
 * 없어요"(풀라)가 화면에서 서로 다른 일을 하지 않는다 — 갈리는 건 다음 행동이다. */
export function ContentListEmptyState({
  message = "조건에 맞는 작품이 없어요.",
  action,
}: {
  message?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
      {action}
    </div>
  );
}
