/**
 * 차트 카드의 키보드 포커스 표시. recharts 는 차트 SVG 를 Tab 으로 들어갈 수 있게 두고, 들어가면 좌우 화살표로 날짜를 옮기며
 * 툴팁에 그날 값을 띄운다 — 눈으로 보는 키보드 사용자에게는 값을 읽는 유일한 길이라 포커스를 빼지 않는다. 공용 툴팁은
 * 라이브 영역이 아니라 스크린리더에는 값이 읽히지 않는다 — 차트마다 `title` 로 이름만 준다. 공용 차트가 SVG 의 윤곽선을 지우므로
 * 포커스는 차트를 담은 카드 테두리에 링으로 그린다.
 */
export const CHART_FOCUS_CLASS =
  "has-[.recharts-surface:focus-visible]:border-ring has-[.recharts-surface:focus-visible]:ring-3 has-[.recharts-surface:focus-visible]:ring-ring/50";
