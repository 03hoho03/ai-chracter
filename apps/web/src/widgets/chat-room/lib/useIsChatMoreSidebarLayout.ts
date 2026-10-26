import { useMedia } from "react-use";

// 더보기 패널은 lg(1024px) 이상에서 인라인 사이드바, 그 미만에서 Sheet로 갈린다.
// CSS 분기(`lg:hidden`)로는 갈 수 없다: Sheet는 body로 포털되므로 부모 클래스가 닿지 않고, 열린
// Sheet는 포커스 트랩·바깥 클릭 차단까지 걸어 데스크톱에서 인라인 패널과 공존할 수 없다. 그래서 JS로
// 판정하며, 헤더의 트리거(ChatMorePanel)와 본문의 사이드바(ChatMoreSidebar)가 같은 값을 봐야 하므로
// 브레이크포인트를 여기 한 곳에 둔다. 같은 1024px를 JS로 가르는 곳은 이 훅만이 아니다 — 이미지
// 스튜디오(useIsImageStudioWideLayout)와 소설 편집 보드도 각자의 훅으로 같은 값을 본다.
// 기본값을 주지 않는다 — 주면 react-use 가 첫 렌더에 matchMedia 를 보지 않아 넓은 화면에서도 Sheet 쪽 트리거를 한 번
// 그린 뒤 사이드바 쪽으로 바뀐다(이 앱은 서버 렌더링이 없어 기본값이 막아 줄 불일치도 없다).
export function useIsChatMoreSidebarLayout() {
  return useMedia("(min-width: 1024px)");
}
