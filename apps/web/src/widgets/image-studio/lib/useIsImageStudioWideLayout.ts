import { useMedia } from "react-use";

// defaultState를 주지 않는다. react-use의 getInitialState는
// defaultState가 있으면 matchMedia를 아예 보지 않아 데스크톱에서도 첫 렌더가 모바일 분기로
// 그려진다(react-use 가 기본값을 받는 이유는 하이드레이션 불일치 방지인데, 이 앱은 SSR이 없다 —
// dist/index.html이 <div id="root"></div> 하나뿐이다). 같은 1024px를 보는 useIsChatMoreSidebarLayout도 같다.
export function useIsImageStudioWideLayout() {
  return useMedia("(min-width: 1024px)");
}
