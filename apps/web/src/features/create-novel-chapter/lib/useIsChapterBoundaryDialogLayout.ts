import { useMedia } from "react-use";

// 장 끝 고르기는 sm(640px) 이상에서 가운데 다이얼로그, 그 미만에서 아래 시트다. CSS 로는 못 가른다 — 둘 다
// body 로 포털되고 열리면 포커스를 가두므로 하나만 마운트돼야 한다. defaultState 를 주지 않는다: 주면 matchMedia 를
// 보지 않고 그 값으로 첫 렌더를 그려, 넓은 화면에서도 시트가 한 번 떴다 사라진다(이 앱은 SSR 이 없다).
export function useIsChapterBoundaryDialogLayout() {
  return useMedia("(min-width: 640px)");
}
