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
 * **로딩 중 비활성은 `disabled`가 아니라 `aria-disabled`다(US-011).** `disabled`를 걸면 브라우저가
 * 그 즉시 버튼을 blur해서 **누를 때마다** `activeElement`가 `<body>`로 떨어진다 — 키보드 사용자는
 * 한 페이지 더 볼 때마다 헤더부터 Tab을 다시 시작하게 된다(WCAG 2.4.3). 실측: 클릭 71ms 뒤 이미
 * `BODY`인데 버튼은 아직 DOM에 있었다(`inDom: true`) — 언마운트가 아니라 `disabled` 자체가 원인이다.
 * base가 `disabled`에 거는 두 클래스를 `aria-disabled`로 그대로 옮겨 온다(`pointer-events-none` +
 * 흐림). `pointer-events`는 **포커스에 관여하지 않으므로** 포인터 클릭과 눌림 모션은 죽이면서 포커스는
 * 남는다 — 이게 `disabled`와 갈리는 지점 전부다. 흐림 값만 base의 50이 아니라 **65**인데, 65는 US-004가
 * **포커스가 닿는** 비활성에 정한 값이다(50은 그때 대비 미달로 기각됐다).
 *
 * 키보드 Enter는 `pointer-events`가 막지 못하므로 중복 실행은 **`handleClick`의 early return**과
 * 호출부의 `isFetchingNextPage` 가드 양쪽이 막는다(호출부 가드만으로는 버튼이 눌리는 것처럼 보이고
 * 아무 일도 안 일어난다).
 *
 * **남은 결함 — 마지막 페이지의 포커스 이관.** 마지막 페이지가 도착하면 이 버튼이 스스로 언마운트되므로
 * 그 순간 `activeElement`가 `<body>`로 떨어진다(실측: 26→32건 도착 시 `isBody: true`). 위 `disabled`
 * 결함과 달리 이건 목록당 딱 한 번이고, 고치려면 (a) US-009 AC가 못박은 "마지막 페이지에서 버튼이
 * 사라진다"를 바꾸거나 (b) 새로 붙은 첫 카드로 포커스를 넘기도록 호출부 둘에 타깃을 배선해야 한다 —
 * 둘 다 설계 결정이라 측정만 남기고 다음 런으로 넘긴다. `MyWorksBody`의 `focusTypeFilter`가 같은
 * 부류의 결함을 "언마운트되지 않는 컨트롤로 미리 옮긴다"로 푼 선례다. */
export function ContentListLoadMore({ hasMore, isLoading, onLoadMore }: ContentListLoadMoreProps) {
  if (!hasMore) return null;

  const handleClick = () => {
    if (isLoading) return;
    onLoadMore();
  };

  return (
    <div className="flex justify-center">
      <Button
        type="button"
        variant="outline"
        aria-disabled={isLoading}
        onClick={handleClick}
        className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
      >
        {isLoading && <Loader2 aria-hidden className="motion-safe:animate-spin" />}
        더 보기
      </Button>
    </div>
  );
}
