import { useMedia } from "react-use";

/** 마우스·트랙패드처럼 hover 가 되고 정밀한 포인터가 주 입력인 기기인가. 페이지 모드는 이런 기기에서만 쪽 좌우에 넘김
 * 버튼 자리를 비우고 버튼을 늘 보인다 — 터치 기기는 탭 영역과 스와이프로 넘기고 버튼은 바와 함께만 나온다.
 * 기본값을 주지 않는다 — 주면 react-use 가 첫 렌더에 matchMedia 를 보지 않아, 쪽 폭을 한 번 버튼 자리 없이 잰 뒤
 * 다시 잰다(이 앱은 서버 렌더링이 없어 기본값이 막아 줄 불일치도 없다). */
export function useIsFinePointer(): boolean {
  return useMedia("(hover: hover) and (pointer: fine)");
}
