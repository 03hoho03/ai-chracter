import { useMedia } from "react-use";

// US-004/005 — 더보기 패널은 lg(1024px) 이상에서 인라인 사이드바, 그 미만에서 Sheet로 갈린다.
// CSS 분기(`lg:hidden`)로는 갈 수 없다: Sheet는 body로 포털되므로 부모 클래스가 닿지 않고, 열린
// Sheet는 포커스 트랩·바깥 클릭 차단까지 걸어 데스크톱에서 인라인 패널과 공존할 수 없다. 그래서 JS로
// 판정하며, 헤더의 트리거(ChatMorePanel)와 본문의 사이드바(ChatMoreSidebar)가 같은 값을 봐야 하므로
// 브레이크포인트를 여기 한 곳에 둔다. DESIGN.md의 sm/md 2단 스케일 밖의 유일한 예외다.
export function useIsChatMoreSidebarLayout() {
  return useMedia("(min-width: 1024px)", false);
}
