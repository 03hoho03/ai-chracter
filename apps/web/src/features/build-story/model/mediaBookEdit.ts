import { normalizeMediaBookName, type MediaBookAxis } from "@/entities/media-book";

import {
  MAX_MEDIA_BOOK_CELLS,
  mediaBookAxisSchema,
  type MediaBookAxisValues,
  type MediaBookCellValues,
  type MediaBookValues,
} from "./schema";

/**
 * 미디어 북 편집을 순수 함수로 모았다. 화면은 이 함수들이 돌려준 **새 미디어 북 전체**를 폼에 통째로 쓴다 —
 * 배열 항목 단위 액션(`useFieldArray`의 remove 등)은 자동저장 구독에 닿지 않을 때가 있어 쓰지 않는다.
 * 모든 함수는 폼 스키마(`mediaBookSchema`)를 통과하는 값만 만든다: 이름은 정규화한 값으로 넣고, 상한·중복은
 * 호출 전에 막는다.
 */

const AXIS_KEY = { person: "people", scene: "scenes" } as const satisfies Record<MediaBookAxis, keyof MediaBookValues>;

export function axisItems(mediaBook: MediaBookValues, axis: MediaBookAxis): MediaBookAxisValues[] {
  return mediaBook[AXIS_KEY[axis]];
}

function cellAxisId(cell: MediaBookCellValues, axis: MediaBookAxis): string {
  return axis === "person" ? cell.personId : cell.sceneId;
}

/**
 * 축 이름 입력의 오류 문구(문제가 없으면 undefined). 길이·금지 문자는 폼 스키마의 문구를 그대로 쓰고, 같은 축의
 * 다른 항목과 정규화 후 같으면 중복이다. `selfId` 는 이름을 바꾸는 항목 자신(자기 이름과는 겹쳐도 된다).
 */
export function mediaBookNameError(
  name: string,
  siblings: readonly MediaBookAxisValues[],
  selfId?: string,
): string | undefined {
  const parsed = mediaBookAxisSchema.shape.name.safeParse(name);
  if (!parsed.success) return parsed.error.issues[0]?.message;
  const normalized = normalizeMediaBookName(name);
  const isTaken = siblings.some((item) => item.id !== selfId && normalizeMediaBookName(item.name) === normalized);
  return isTaken ? "같은 이름이 이미 있어요" : undefined;
}

export function addAxisItem(mediaBook: MediaBookValues, axis: MediaBookAxis, name: string, id: string): MediaBookValues {
  const key = AXIS_KEY[axis];
  return { ...mediaBook, [key]: [...mediaBook[key], { id, name: normalizeMediaBookName(name) }] };
}

export function renameAxisItem(mediaBook: MediaBookValues, axis: MediaBookAxis, id: string, name: string): MediaBookValues {
  const key = AXIS_KEY[axis];
  return {
    ...mediaBook,
    [key]: mediaBook[key].map((item) => (item.id === id ? { ...item, name: normalizeMediaBookName(name) } : item)),
  };
}

/** 축 항목을 지우면 그 줄의 칸도 함께 지운다 — 남겨 두면 없는 축을 가리키는 칸이 되어 저장이 거절된다. */
export function removeAxisItem(mediaBook: MediaBookValues, axis: MediaBookAxis, id: string): MediaBookValues {
  const key = AXIS_KEY[axis];
  return {
    ...mediaBook,
    [key]: mediaBook[key].filter((item) => item.id !== id),
    cells: mediaBook.cells.filter((cell) => cellAxisId(cell, axis) !== id),
  };
}

export function countAxisItemCells(mediaBook: MediaBookValues, axis: MediaBookAxis, id: string): number {
  return mediaBook.cells.filter((cell) => cellAxisId(cell, axis) === id).length;
}

export function findCell(
  mediaBook: MediaBookValues,
  personId: string,
  sceneId: string,
): MediaBookCellValues | undefined {
  return mediaBook.cells.find((cell) => cell.personId === personId && cell.sceneId === sceneId);
}

export type MediaBookCellImage = {
  assetId: string;
  imageUrl?: string;
  imageWidth?: number;
  imageHeight?: number;
};

/** 칸에 그림을 넣지 못한 이유. 화면이 이유마다 다른 문장으로 알린다. */
/** `renamed-axis` 는 일괄 업로드만 낸다 — 파일 이름이 가리키던 인물·장면이 올리는 동안 다른 이름으로 바뀐 경우. */
export type CellImageRefusal = "cap" | "missing-axis" | "renamed-axis";

const CELL_IMAGE_REFUSAL_MESSAGE = {
  cap: `미디어 북 이미지는 ${MAX_MEDIA_BOOK_CELLS}장까지 넣을 수 있어요`,
  "missing-axis": "그림을 올리는 동안 이 칸의 인물이나 장면이 지워져서 넣지 않았어요",
  "renamed-axis": "그림을 올리는 동안 이 칸의 인물이나 장면 이름이 바뀌어서 넣지 않았어요",
} as const satisfies Record<CellImageRefusal, string>;

export function cellImageRefusalMessage(reason: CellImageRefusal): string {
  return CELL_IMAGE_REFUSAL_MESSAGE[reason];
}

export type CellImageResult = { ok: true; mediaBook: MediaBookValues } | { ok: false; reason: CellImageRefusal };

/**
 * 한 칸에 그림을 넣는다. 이미 채워진 칸이면 **칸 id 를 그대로 두고 그림만 바꾼다** — id 가 바뀌면 플레이어의 해금
 * 기록과 대화방 첫 메시지의 태그가 옛 칸을 가리켜 끊긴다. 빈 칸이면 새 id 로 칸을 만든다.
 *
 * 거절하는 경우 둘(값은 바꾸지 않는다):
 * - 그 칸의 인물이나 장면이 미디어 북에 없다 — 업로드를 기다리는 사이 축이 지워진 경우다. 만들면 없는 축을 가리키는
 *   칸이 되어 폼 스키마를 어기고, 그 뒤 미디어 북 전체가 자동저장에서 빠진다(그 칸은 표에 보이지 않아 지울 수도 없다).
 * - 새 칸인데 상한에 닿았다.
 */
export function setCellImage(
  mediaBook: MediaBookValues,
  personId: string,
  sceneId: string,
  image: MediaBookCellImage,
  createId: () => string,
): CellImageResult {
  const hasAxes =
    mediaBook.people.some((person) => person.id === personId) && mediaBook.scenes.some((scene) => scene.id === sceneId);
  if (!hasAxes) return { ok: false, reason: "missing-axis" };
  const imageFields = {
    imageAssetId: image.assetId,
    imageUrl: image.imageUrl,
    imageWidth: image.imageWidth,
    imageHeight: image.imageHeight,
  };
  const existing = findCell(mediaBook, personId, sceneId);
  if (existing) {
    return {
      ok: true,
      mediaBook: {
        ...mediaBook,
        cells: mediaBook.cells.map((cell) => (cell.id === existing.id ? { ...cell, ...imageFields } : cell)),
      },
    };
  }
  if (mediaBook.cells.length >= MAX_MEDIA_BOOK_CELLS) return { ok: false, reason: "cap" };
  const cell: MediaBookCellValues = {
    id: createId(),
    personId,
    sceneId,
    ...imageFields,
    situationDescription: "",
    unlockHint: "",
    excludeFromChat: false,
  };
  return { ok: true, mediaBook: { ...mediaBook, cells: [...mediaBook.cells, cell] } };
}

export type MediaBookCellTextPatch = Partial<
  Pick<MediaBookCellValues, "situationDescription" | "unlockHint" | "excludeFromChat">
>;

export function updateCell(mediaBook: MediaBookValues, cellId: string, patch: MediaBookCellTextPatch): MediaBookValues {
  return { ...mediaBook, cells: mediaBook.cells.map((cell) => (cell.id === cellId ? { ...cell, ...patch } : cell)) };
}

export function removeCell(mediaBook: MediaBookValues, cellId: string): MediaBookValues {
  return { ...mediaBook, cells: mediaBook.cells.filter((cell) => cell.id !== cellId) };
}

/** 이름(정규화 후 비교)으로 축 항목을 찾고, 없으면 만든다. 이름은 이미 검사를 통과한 값이어야 한다. */
export function ensureAxisItem(
  mediaBook: MediaBookValues,
  axis: MediaBookAxis,
  name: string,
  createId: () => string,
): { mediaBook: MediaBookValues; id: string } {
  const normalized = normalizeMediaBookName(name);
  const found = axisItems(mediaBook, axis).find((item) => normalizeMediaBookName(item.name) === normalized);
  if (found) return { mediaBook, id: found.id };
  const id = createId();
  return { mediaBook: addAxisItem(mediaBook, axis, normalized, id), id };
}
