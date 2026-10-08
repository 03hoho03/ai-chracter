import { NOTES_NODE_KEY, characterNodeKey, episodeNodeKey } from "./boardNode";

/** 편집 보드에서 고른 것. 주소의 `?select=` 하나가 정하고, 값은 배치 저장 키와 같은 말이다(`episode:{id}`·
 * `character:{id}`·`notes`) — 거기에 버전 패널(`versions`)이 더해진다. 없으면 고른 것 없음(소설 개요)이다. */
export type BoardSelection =
  | { kind: "episode"; id: string }
  | { kind: "character"; id: string }
  | { kind: "notes" }
  | { kind: "versions" };

export const VERSIONS_SELECT_VALUE = "versions";

const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const EPISODE_PATTERN = new RegExp(`^episode:(${UUID})$`);
const CHARACTER_PATTERN = new RegExp(`^character:(${UUID})$`);

/** 주소 값을 고른 것으로 편다. 모르는 꼴(손으로 고친 주소·옛 링크)은 `undefined`(고른 것 없음)로 접는다 — 던지면
 * 화면이 통째로 죽는다. */
export function parseBoardSelection(value: string | undefined): BoardSelection | undefined {
  if (value === undefined) return undefined;
  if (value === NOTES_NODE_KEY) return { kind: "notes" };
  if (value === VERSIONS_SELECT_VALUE) return { kind: "versions" };
  const episode = EPISODE_PATTERN.exec(value)?.[1];
  if (episode !== undefined) return { kind: "episode", id: episode };
  const character = CHARACTER_PATTERN.exec(value)?.[1];
  if (character !== undefined) return { kind: "character", id: character };
  return undefined;
}

/** 고른 것을 주소 값으로. 노드가 있는 것은 노드 키와 같다. */
export function toBoardSelectValue(selection: BoardSelection): string {
  switch (selection.kind) {
    case "episode":
      return episodeNodeKey(selection.id);
    case "character":
      return characterNodeKey(selection.id);
    case "notes":
      return NOTES_NODE_KEY;
    case "versions":
      return VERSIONS_SELECT_VALUE;
  }
}

/** 고른 것이 캔버스의 어느 노드인가. 버전 패널은 노드가 없다. */
export function toSelectedNodeKey(selection: BoardSelection | undefined): string | undefined {
  if (selection === undefined || selection.kind === "versions") return undefined;
  return toBoardSelectValue(selection);
}

/** 지금 없는 대상(지운 화·합쳐 사라진 인물)을 고른 주소는 고른 것 없음으로 접는다. 인물 목록을 아직 받지 못했으면
 * (`undefined`) 인물은 있는 것으로 두고 패널이 기다린다 — 그사이 개요로 튀었다가 돌아오지 않게. */
export function resolveBoardSelection(
  selection: BoardSelection | undefined,
  chapterIds: readonly string[],
  characterIds: readonly string[] | undefined,
): BoardSelection | undefined {
  if (selection === undefined) return undefined;
  if (selection.kind === "episode") return chapterIds.includes(selection.id) ? selection : undefined;
  if (selection.kind === "character") {
    if (characterIds === undefined) return selection;
    return characterIds.includes(selection.id) ? selection : undefined;
  }
  return selection;
}

/** 노드 키 → 고른 것. 캔버스가 알려 오는 고르기(노드 키)를 주소로 옮길 때 쓴다. 묶음 테두리처럼 고를 수 없는 키는
 * `undefined`. */
export function nodeKeyToSelection(nodeKey: string): BoardSelection | undefined {
  const selection = parseBoardSelection(nodeKey);
  return selection?.kind === "versions" ? undefined : selection;
}
