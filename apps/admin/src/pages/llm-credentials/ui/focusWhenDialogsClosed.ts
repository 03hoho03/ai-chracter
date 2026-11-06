/** 대화상자가 닫히는 동안 포커스 이동을 미루는 최대 프레임 수. 넘기면 그냥 옮긴다. */
const MAX_WAIT_FRAMES = 120;

/**
 * 대화상자가 모두 닫히고 대상이 화면에 생긴 뒤 그 요소로 포커스를 옮긴다 — 열린 대화상자의 포커스 가두기가 밖으로 나간 포커스를
 * 되돌리고, 방금 추가한 항목은 목록이 다시 그려진 뒤에야 생긴다. 대화상자 래퍼는 포커스를 잃었을 때만 연 버튼으로 돌려주므로 이
 * 이동과 다투지 않는다(래퍼가 먼저 돌려줘도 이 이동이 뒤따라 옮긴다).
 */
export function focusWhenDialogsClosed(elementId: string) {
  let frames = 0;
  const tick = () => {
    frames += 1;
    const target = document.getElementById(elementId);
    const isOverlayOpen = document.querySelector('[role="dialog"], [role="alertdialog"]') !== null;
    if ((target === null || isOverlayOpen) && frames < MAX_WAIT_FRAMES) {
      requestAnimationFrame(tick);
      return;
    }
    target?.focus();
  };
  requestAnimationFrame(tick);
}
