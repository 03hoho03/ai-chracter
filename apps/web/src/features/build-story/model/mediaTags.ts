import { normalizeMediaBookName, type MediaBookValues, type StoryBuilderFormValues } from "./schema";

/**
 * 빌더 글 속 미디어 북 태그 `{{img::인물/장면}}`(이름 형태)를 다루는 순수 함수들.
 *
 * 태그 읽기 규칙은 서버(`apps/api/src/api/content/media_tags.py`)와 같다 — 본문에 슬래시가 정확히 하나여야 이름
 * 형태이고, 인물·장면은 앞뒤 공백 제거 + NFC 로 비교한다. 서버는 줄 단위로 읽으므로 줄을 넘는 본문도 태그가 아니다.
 * 그 밖의 `{{…}}`(칸 id 형태, 슬래시가 없거나 둘인 것, `{{user}}` 같은 다른 문법)는 글이라 손대지 않는다.
 */
const MEDIA_TAG = /\{\{img::([^{}\n]*)\}\}/g;

export type MediaBookAxis = "person" | "scene";

type ParsedNameTag = { person: string; scene: string };

function parseNameTagBody(body: string): ParsedNameTag | undefined {
  const parts = body.split("/");
  if (parts.length !== 2) return undefined;
  const [person = "", scene = ""] = parts;
  return { person: normalizeMediaBookName(person), scene: normalizeMediaBookName(scene) };
}

/** 칸을 가리키는 이름 형태 태그. 이름은 이미 정규화된(저장된) 값을 받는다. */
export function toMediaTag(personName: string, sceneName: string): string {
  return `{{img::${personName}/${sceneName}}}`;
}

/** 글에 이미지 태그(어느 형태든)가 들어 있는가 — 태그가 그림이 되지 않는 칸의 경고에 쓴다. */
export function hasMediaTag(text: string | undefined): boolean {
  return text !== undefined && text.includes("{{img::");
}

/**
 * 인물이나 장면 이름이 바뀌었을 때 글 속 이름 형태 태그를 새 이름으로 바꾼다. 태그 안에서 그 축 자리의 이름이
 * 정확히 같을 때만 바꾼다 — 글자열 치환이 아니므로 `리아`를 바꿔도 `마리아`가 든 태그나 태그 밖 글은 그대로다.
 */
export function renameMediaTagName(text: string, axis: MediaBookAxis, oldName: string, newName: string): string {
  if (!text.includes("{{img::")) return text;
  const from = normalizeMediaBookName(oldName);
  const to = normalizeMediaBookName(newName);
  return text.replace(MEDIA_TAG, (match, body: string) => {
    const parsed = parseNameTagBody(body);
    if (parsed === undefined || parsed[axis] !== from) return match;
    return axis === "person" ? toMediaTag(to, parsed.scene) : toMediaTag(parsed.person, to);
  });
}

/**
 * 글 속 이름 형태 태그 중 미디어 북에 그림이 있는 칸을 가리키지 않는 것(오타·지운 칸·빈 칸)을 원문 그대로,
 * 나온 순서대로 중복 없이 돌려준다. 화면은 이런 태그를 빈칸으로 둔다.
 */
export function findUnknownMediaTags(text: string | undefined, mediaBook: MediaBookValues): string[] {
  if (text === undefined || !text.includes("{{img::")) return [];
  const personIdByName = new Map(mediaBook.people.map((person) => [normalizeMediaBookName(person.name), person.id]));
  const sceneIdByName = new Map(mediaBook.scenes.map((scene) => [normalizeMediaBookName(scene.name), scene.id]));
  const filled = new Set(mediaBook.cells.map((cell) => `${cell.personId}|${cell.sceneId}`));
  const unknown: string[] = [];
  for (const match of text.matchAll(MEDIA_TAG)) {
    const parsed = parseNameTagBody(match[1] ?? "");
    if (parsed === undefined) continue;
    const personId = personIdByName.get(parsed.person);
    const sceneId = sceneIdByName.get(parsed.scene);
    const isFilled = personId !== undefined && sceneId !== undefined && filled.has(`${personId}|${sceneId}`);
    if (!isFilled && !unknown.includes(match[0])) unknown.push(match[0]);
  }
  return unknown;
}

export type TextSelection = { text: string; selectionStart: number; selectionEnd: number };

/** 커서 자리(고른 글이 있으면 그 글 대신)에 태그를 넣고 캐럿을 태그 바로 뒤에 둔다. */
export function insertMediaTag({ text, selectionStart, selectionEnd }: TextSelection, tag: string): TextSelection {
  const from = Math.min(selectionStart, selectionEnd);
  const to = Math.max(selectionStart, selectionEnd);
  const caret = from + tag.length;
  return { text: text.slice(0, from) + tag + text.slice(to), selectionStart: caret, selectionEnd: caret };
}

/** 태그가 그림이 되는 빌더 글 네 종류 — 모든 시작설정의 시작상황·프롤로그, 모든 엔딩의 에필로그, 등록 설명. */
export type MediaTagFieldPath =
  | `startingSetups.${number}.openingSituation`
  | `startingSetups.${number}.prologue`
  | `startingSetups.${number}.endings.${number}.epilogue`
  | "registration.description";

export type MediaTagFieldChange = { path: MediaTagFieldPath; value: string };

/**
 * 이름을 바꾼 축의 태그를 태그가 그림이 되는 글 전부(시작설정·엔딩이 여럿이면 그 전부)에서 바꾼다. 실제로 바뀐
 * 글만 돌려준다 — 호출부가 바뀐 칸에만 값을 쓰게 한다.
 */
export function renameMediaTagsInFields(
  values: Pick<StoryBuilderFormValues, "startingSetups" | "registration">,
  axis: MediaBookAxis,
  oldName: string,
  newName: string,
): MediaTagFieldChange[] {
  const changes: MediaTagFieldChange[] = [];
  const push = (path: MediaTagFieldPath, text: string | undefined) => {
    if (text === undefined) return;
    const next = renameMediaTagName(text, axis, oldName, newName);
    if (next !== text) changes.push({ path, value: next });
  };
  values.startingSetups.forEach((setup, setupIndex) => {
    push(`startingSetups.${setupIndex}.openingSituation`, setup.openingSituation);
    push(`startingSetups.${setupIndex}.prologue`, setup.prologue);
    setup.endings.forEach((ending, endingIndex) => {
      push(`startingSetups.${setupIndex}.endings.${endingIndex}.epilogue`, ending.epilogue);
    });
  });
  push("registration.description", values.registration.description);
  return changes;
}
