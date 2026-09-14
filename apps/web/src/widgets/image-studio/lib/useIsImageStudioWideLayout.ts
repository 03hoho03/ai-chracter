import { useMedia } from "react-use";

// image-refact-techspec.md IT-8 — defaultState를 주지 않는다. react-use의 getInitialState는
// defaultState가 있으면 matchMedia를 아예 보지 않아 데스크톱에서도 첫 렌더가 모바일 분기로
// 그려진다(useIsChatMoreSidebarLayout이 그 값을 준 이유는 하이드레이션 불일치 방지인데, 이 앱은
// SSR이 없다 — dist/index.html이 <div id="root"></div> 하나뿐이다). 그래서 저 훅은 고치지 않고
// (채팅 재검증이 필요한 범위 밖이다) 이 훅만 defaultState 없이 새로 둔다.
export function useIsImageStudioWideLayout() {
  return useMedia("(min-width: 1024px)");
}
