import { Button } from "@ai-character-chat/ui/components/button";
import { Loader2 } from "lucide-react";

type ContentListLoadMoreProps = {
  /** 서버가 다음 커서를 줬을 때만 true. false면 이 컴포넌트는 아무것도 그리지 않는다. */
  hasMore: boolean;
  isLoading: boolean;
  onLoadMore: () => void;
};

/** US-009 — `/my`·프로필 목록의 "더 보기". 홈·즐겨찾기의 sentinel 무한스크롤과 **일부러 다르다**:
 * 이 두 화면은 작가가 자기 작품을 관리하는 곳이라 목록 아래에 끝이 있어야 하고(스크롤이 계속 늘어나면
 * 마지막 항목에 도달했는지 알 수 없다), 명시적 버튼이 PRD의 확정 사항이다.
 *
 * `variant="outline"`인 이유: DESIGN.md §2가 `primary` 솔리드를 이 시스템의 유일한 유채색 솔리드
 * 채움으로 못박았고 그 자리는 두 화면 모두 `작품 만들기`가 이미 갖고 있다 — 목록을 늘리는 건 그보다
 * 약한 보조 동작이다.
 *
 * 중복 클릭은 `disabled`(포인터 이벤트까지 죽는다)와 호출부의 `isFetchingNextPage` 가드 **양쪽**이
 * 막는다 — 호출부 가드만으로는 버튼이 눌리는 것처럼 보이고 아무 일도 안 일어난다.
 *
 * **알려진 남은 결함(US-011의 접근성 스윕에서 잴 것):** 마지막 페이지가 도착하면 이 버튼이 스스로
 * 언마운트되므로 그 순간 `activeElement`가 `<body>`로 떨어진다(키보드 사용자의 다음 Tab이 헤더부터
 * 다시 시작한다 — `MyWorksBody`의 `focusTypeFilter`가 같은 이유로 존재한다). 여기서는 US-009 AC의
 * "마지막 페이지에서 버튼이 사라진다"를 그대로 지키고, 포커스 이관 처방은 실측 뒤에 정한다. */
export function ContentListLoadMore({ hasMore, isLoading, onLoadMore }: ContentListLoadMoreProps) {
  if (!hasMore) return null;

  return (
    <div className="flex justify-center">
      <Button type="button" variant="outline" disabled={isLoading} onClick={onLoadMore}>
        {isLoading && <Loader2 aria-hidden className="motion-safe:animate-spin" />}
        더 보기
      </Button>
    </div>
  );
}
