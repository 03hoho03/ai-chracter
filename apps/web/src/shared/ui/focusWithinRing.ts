/**
 * 파일 고르기 버튼처럼 `<Label>` 이 화면에서 감춘(`sr-only`) file input 을 감싸는 자리의 포커스 링.
 * Tab 으로 포커스를 받는 건 보이지 않는 input 이라 input 에 링을 달면 아무것도 안 보인다 —
 * 그래서 보이는 라벨이 "안에 키보드 포커스를 받은 input 이 있을 때" 링을 대신 그린다.
 * 링 두께·색은 `button.tsx` 의 `focus-visible` 링과 같은 세 토큰이다.
 * 비활성 표현(`has-disabled:`·`aria-disabled:`)은 자리마다 달라 여기에 묶지 않는다.
 */
export const FOCUS_WITHIN_RING_CLASSNAME =
  "has-[input:focus-visible]:border-ring has-[input:focus-visible]:ring-3 has-[input:focus-visible]:ring-ring/50";
