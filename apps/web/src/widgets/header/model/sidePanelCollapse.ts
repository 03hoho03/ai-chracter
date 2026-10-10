/** 좌측 패널(lg 이상)의 접힘을 정하는 규칙. 상태는 둘이다 — 사용자가 토글로 남긴 저장값과, 채팅·이미지 스튜디오에
 * 있는 동안만 사는 그 화면의 임시값.
 *
 * - 채팅·이미지 스튜디오는 본문 가운데 열이 넓어야 하는 화면이라 바깥에서 들어오면 저장값과 무관하게 접힌 채로
 *   시작하고, 거기서 펴거나 접은 것은 저장하지 않는다(그 화면을 떠나면 잊는다).
 * - 같은 종류 안에서 옮길 때(패널의 최근 대화로 다른 방에 가는 것)는 그 화면의 임시값을 이어 간다. 방을 옮길 때마다
 *   접으면 펼친 패널을 대화 전환기로 쓰는 흐름이 매번 끊긴다.
 * - 그 밖의 화면은 저장값을 따르고, 저장값이 없으면 xl(1280px) 이상은 펼침, 그 아래는 접힘이다. 저장값이 없을 때는
 *   창 크기가 바뀌면 그 판정도 따라 바뀐다. */

export type SidePanelScreen = "chat" | "image-studio" | "other";

const CHAT_ROOM_PATH = /^\/chat\/[^/]+$/;

export function getSidePanelScreen(pathname: string): SidePanelScreen {
  if (CHAT_ROOM_PATH.test(pathname)) return "chat";
  if (pathname === "/studio/images") return "image-studio";
  return "other";
}

/** 화면이 바뀐 뒤의 임시값. 처음 그리는 화면은 `previousScreen` 이 없다 — 새로고침도 바깥에서 들어온 것으로 본다.
 * 채팅에서 이미지 스튜디오로(또는 그 반대로) 가는 것도 다른 화면에 들어오는 것이라 접힘으로 시작한다. */
export function getNextScreenCollapsed(
  previousScreen: SidePanelScreen | undefined,
  screen: SidePanelScreen,
  screenCollapsed: boolean | undefined,
): boolean | undefined {
  if (screen === "other") return undefined;
  if (screen === previousScreen) return screenCollapsed;
  return true;
}

export function resolveSidePanelCollapsed({
  savedCollapsed,
  screenCollapsed,
  isWide,
}: {
  savedCollapsed: boolean | undefined;
  screenCollapsed: boolean | undefined;
  isWide: boolean;
}): boolean {
  return screenCollapsed ?? savedCollapsed ?? !isWide;
}

/** 토글 한 번의 결과. 저장할지는 화면이 정한다 — 채팅·이미지 스튜디오에서 바꾼 것은 그 화면의 임시값으로만 둔다. */
export function toggleSidePanelCollapsed(
  screen: SidePanelScreen,
  isCollapsed: boolean,
): { isCollapsed: boolean; shouldSave: boolean } {
  return { isCollapsed: !isCollapsed, shouldSave: screen === "other" };
}

const SIDE_PANEL_COLLAPSED_STORAGE_KEY = "side-panel-collapsed";

type SidePanelStorage = Pick<Storage, "getItem" | "setItem">;

/** 사이트 데이터가 차단된 브라우저에서는 `localStorage` 참조 자체가 던진다 — 읽기·쓰기 함수가 함께 삼킨다. */
function browserStorage(): SidePanelStorage {
  return window.localStorage;
}

/** 저장값은 `"1"`(접힘)·`"0"`(펼침) 둘뿐이다. 그 밖의 값은 저장값이 없는 것으로 본다. */
export function parseSidePanelCollapsed(raw: string | null | undefined): boolean | undefined {
  if (raw === "1") return true;
  if (raw === "0") return false;
  return undefined;
}

/** 못 읽으면(저장소 막힘 포함) 저장값이 없는 것으로 본다 — 폭 기본값으로 그린다. */
export function readSavedSidePanelCollapsed(getStorage: () => SidePanelStorage = browserStorage): boolean | undefined {
  try {
    return parseSidePanelCollapsed(getStorage().getItem(SIDE_PANEL_COLLAPSED_STORAGE_KEY));
  } catch {
    return undefined;
  }
}

/** 저장하지 못하면 이번 방문에만 남고 다음 방문은 폭 기본값으로 돌아간다. */
export function writeSavedSidePanelCollapsed(
  isCollapsed: boolean,
  getStorage: () => SidePanelStorage = browserStorage,
): void {
  try {
    getStorage().setItem(SIDE_PANEL_COLLAPSED_STORAGE_KEY, isCollapsed ? "1" : "0");
  } catch {
    // 저장하지 못해도 화면의 접힘은 바뀐다.
  }
}
