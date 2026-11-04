/**
 * 요소를 가장 가까운 세로 스크롤 조상 안에 들인다 — `scrollIntoView({ block: "nearest" })` 와 같은 자리로, 이미 보이면 움직이지
 * 않는다. 그 함수를 쓰지 않는 것은 Chromium 에서 순차 초점 이동의 시작점까지 그 요소로 옮기기 때문이다: 포커스를 옮길 뜻이 없는
 * 스크롤(고른 턴 따라가기)이 다음 Tab 의 출발점을 바꿔, 화면을 연 직후 첫 Tab 이 헤더를 건너뛴다. 스크롤 컨테이너의 `scrollTop`
 * 만 맞추면 시작점은 그대로다. 포커스도 함께 옮기는 곳(j/k)은 어차피 그 요소가 출발점이라 이것을 쓸 까닭이 없다.
 */
export function scrollIntoNearest(target: HTMLElement): void {
  const scroller = scrollParent(target);
  if (scroller === null) return;
  const box = target.getBoundingClientRect();
  const frame = scroller.getBoundingClientRect();
  if (box.top < frame.top) scroller.scrollTop -= frame.top - box.top;
  else if (box.bottom > frame.bottom) scroller.scrollTop += box.bottom - frame.bottom;
}

function scrollParent(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node !== null; node = node.parentElement) {
    const { overflowY } = window.getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") return node;
  }
  return null;
}
