import { findMediaNameTags, normalizeMediaBookName, renameMediaTagName, type MediaBookAxis } from "@/entities/media-book";

import type { MediaBookValues, StoryBuilderFormValues } from "./schema";

/**
 * 빌더 글 속 미디어 북 태그를 폼 값에 맞춰 다루는 함수들. 태그 문법(무엇이 이름 형태 태그인가, 이름을 어떻게
 * 정규화하는가, 이름 바꾸기)은 `entities/media-book` 이 서버와 같은 규칙으로 한 곳에 갖고 있고, 여기는 그 결과를
 * 빌더의 미디어 북 표·글 칸 경로에 잇는다.
 */

/**
 * 글 속 이름 형태 태그 중 미디어 북에 그림이 있는 칸을 가리키지 않는 것(오타·지운 칸·빈 칸)을 원문 그대로,
 * 나온 순서대로 중복 없이 돌려준다. 화면은 이런 태그를 빈칸으로 둔다.
 */
export function findUnknownMediaTags(text: string | undefined, mediaBook: MediaBookValues): string[] {
  if (text === undefined) return [];
  const tags = findMediaNameTags(text);
  if (tags.length === 0) return [];
  const personIdByName = new Map(mediaBook.people.map((person) => [normalizeMediaBookName(person.name), person.id]));
  const sceneIdByName = new Map(mediaBook.scenes.map((scene) => [normalizeMediaBookName(scene.name), scene.id]));
  const filled = new Set(mediaBook.cells.map((cell) => `${cell.personId}|${cell.sceneId}`));
  const unknown: string[] = [];
  for (const tag of tags) {
    const personId = personIdByName.get(tag.person);
    const sceneId = sceneIdByName.get(tag.scene);
    const isFilled = personId !== undefined && sceneId !== undefined && filled.has(`${personId}|${sceneId}`);
    if (!isFilled && !unknown.includes(tag.original)) unknown.push(tag.original);
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
