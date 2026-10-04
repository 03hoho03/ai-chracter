/**
 * 확인 모달의 첫 포커스 대상을 `data-initial-focus` 표식으로 정한다 — `DialogContent` 의 `onOpenAutoFocus` 에 넘긴다.
 *
 * `autoFocus` 만으로는 시트(하단 조치 시트 등) 안에서 연 모달에서 첫 포커스가 빗나간다. React 가 `autoFocus` 요소에
 * 포커스를 주는 순간은 모달의 포커스 범위가 자리를 잡기 전이라, 아직 활성인 시트의 포커스 트랩이 "시트 밖으로 나간
 * 포커스"로 보고 되돌려 놓는다. 그 뒤 모달이 열리며 첫 탭 요소(닫기 X)를 고른다. 이 핸들러는 모달의 포커스 범위가
 * 자리를 잡은 뒤에 불려 시트에 막히지 않는다. 시트 밖에서 열면 `autoFocus` 가 이미 포커스를 줘 이 핸들러는 불리지
 * 않으므로, 표식과 `autoFocus` 를 함께 단다.
 */
export function focusInitialElement(event: Event) {
  if (!(event.currentTarget instanceof HTMLElement)) return;
  const target = event.currentTarget.querySelector<HTMLElement>("[data-initial-focus]");
  if (!target) return;
  event.preventDefault();
  target.focus();
}
