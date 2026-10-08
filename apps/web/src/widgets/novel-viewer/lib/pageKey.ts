/** 키를 누른 순간 포커스가 있는 자리. 호출부가 DOM 에서 가린다 — 입력칸(`text`), 슬라이더(`slider`), 버튼·링크
 * (`control`), 보기 설정 패널·목차 시트 안(`panel`), 그 밖(`none`). */
export type PageKeyFocus = "text" | "slider" | "control" | "panel" | "none";

export type PageKeyAction = "previous" | "next" | "first" | "last";

const ACTION_BY_KEY: Partial<Record<string, PageKeyAction>> = {
  ArrowLeft: "previous",
  ArrowRight: "next",
  PageUp: "previous",
  PageDown: "next",
  Home: "first",
  End: "last",
};

/**
 * 페이지 모드의 넘김 키. 포커스가 있는 요소가 같은 키를 스스로 쓰는 자리에서는 넘기지 않는다 — 입력칸은 커서 이동,
 * 슬라이더는 값 바꾸기, 설정 패널·목차 시트는 그 안의 이동이라 함께 넘기면 한 번 눌러 두 번 움직인다. `Space` 는
 * 버튼·링크에서 그 요소를 누르는 키라 거기서도 넘기지 않는다. Ctrl·Meta·Alt 가 함께 눌렸으면 브라우저·시스템
 * 단축키라 건드리지 않는다. `Shift+Space` 는 이전 쪽이다(문서 스크롤의 위로와 같은 뜻).
 */
export function toPageKeyAction({
  key,
  shiftKey,
  hasModifier,
  focus,
}: {
  key: string;
  shiftKey: boolean;
  /** Ctrl·Meta·Alt 중 하나라도 눌렸는가. */
  hasModifier: boolean;
  focus: PageKeyFocus;
}): PageKeyAction | undefined {
  if (hasModifier || focus === "text" || focus === "slider" || focus === "panel") return undefined;
  if (key === " ") {
    if (focus === "control") return undefined;
    return shiftKey ? "previous" : "next";
  }
  return ACTION_BY_KEY[key];
}
