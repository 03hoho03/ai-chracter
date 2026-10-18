/** 채팅 상태 줄(스탯 게이지 줄)의 접힘 저장. 기기 하나에 값 하나다 — 방마다 따로 두지 않는다. 오래 플레이하는 사람은
 * 접은 채로 두는데, 방을 옮길 때마다 다시 접게 하면 그 선택이 매번 끊긴다. */

const STATUS_LINE_COLLAPSED_STORAGE_KEY = "ttona.chatStatusLine.collapsed";

type StatusLineStorage = Pick<Storage, "getItem" | "setItem">;

/** 사이트 데이터가 차단된 브라우저에서는 `localStorage` 참조 자체가 던진다 — 읽기·쓰기 함수가 함께 삼킨다. */
function browserStorage(): StatusLineStorage {
  return window.localStorage;
}

/** 저장값 `"1"` 만 접힘이다. 없거나, 모르는 값이거나, 못 읽으면 기본인 펼침으로 그린다. */
export function readStatusLineCollapsed(getStorage: () => StatusLineStorage = browserStorage): boolean {
  try {
    return getStorage().getItem(STATUS_LINE_COLLAPSED_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

/** 저장하지 못하면 이번 화면에만 남고 다음 방문은 펼침으로 돌아간다. */
export function writeStatusLineCollapsed(
  isCollapsed: boolean,
  getStorage: () => StatusLineStorage = browserStorage,
): void {
  try {
    getStorage().setItem(STATUS_LINE_COLLAPSED_STORAGE_KEY, isCollapsed ? "1" : "0");
  } catch {
    // 저장하지 못해도 화면의 접힘은 바뀐다.
  }
}
