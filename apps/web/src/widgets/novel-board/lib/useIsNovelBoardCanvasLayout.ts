import { useMedia } from "react-use";

// 편집 보드는 lg(1024px) 이상에서 캔버스 + 오른쪽 패널, 그 미만에서 세로 흐름 목록 + 목록 자리의 패널로 갈린다.
// CSS 로 숨겨 둘 수 없다 — 좁은 화면에서는 캔버스 라이브러리를 마운트하지도 내려받지도 않아야 해서 둘 중 하나만
// 그린다. 캔버스·목록·패널 자리가 같은 값을 봐야 하므로 브레이크포인트를 여기 한 곳에 둔다.
// 기본값을 주지 않는다 — 주면 react-use 가 첫 렌더에 matchMedia 를 보지 않아 넓은 화면에서도 목록을 한 번 그린 뒤
// 캔버스로 바뀐다(이 앱은 서버 렌더링이 없어 기본값이 막아 줄 불일치도 없다).
export function useIsNovelBoardCanvasLayout() {
  return useMedia("(min-width: 1024px)");
}
