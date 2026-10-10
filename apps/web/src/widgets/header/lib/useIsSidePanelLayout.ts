import { useMedia } from "react-use";

/** 좌측 패널을 마운트하는 폭(`lg` 이상). 미디어 쿼리 문자열은 CSS `lg:` 와 같은 `64rem` 이다 — 헤더 로고의 `lg:hidden`
 * 과 이 판정이 같은 경계여야 하는데, 브라우저 기본 글꼴이 16px 가 아니면 `1024px` 과 `64rem` 이 갈려 로고가 둘이거나
 * 패널도 버거도 없는 구간이 생긴다. 그래서 다른 `1024px` 훅을 재사용하지 않는다.
 *
 * `useMedia` 에 기본값을 주지 않는다 — 기본값이 있으면 react-use 가 첫 렌더에 `matchMedia` 를 보지 않아 넓은 화면에서도
 * 패널 없이 한 번 그린다. 이 앱은 SSR 이 없어 첫 렌더부터 실제 값을 읽어도 된다. */
export function useIsSidePanelLayout(): boolean {
  return useMedia("(min-width: 64rem)");
}
