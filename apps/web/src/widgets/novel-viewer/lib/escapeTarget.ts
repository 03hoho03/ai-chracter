/** Esc 한 번이 닫을 것. 가장 위의 것 하나만 닫는다 — 목차 시트가 열려 있으면 시트가 스스로 닫히므로 읽기 화면은 아무
 * 것도 닫지 않고(바까지 숨기면 시트가 돌려줄 "목차" 버튼이 숨은 바 안에 갇힌다), 그다음 보기 설정, 그다음 바다.
 * 판단은 키를 누른 순간의 열림 상태로 한다. */
export function toEscapeTarget({
  isTocOpen,
  isSettingsOpen,
  isChromeVisible,
}: {
  isTocOpen: boolean;
  isSettingsOpen: boolean;
  isChromeVisible: boolean;
}): "none" | "settings" | "chrome" {
  if (isTocOpen) return "none";
  if (isSettingsOpen) return "settings";
  if (isChromeVisible) return "chrome";
  return "none";
}
