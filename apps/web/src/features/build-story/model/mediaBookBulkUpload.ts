import { normalizeMediaBookName, type MediaBookAxis, type OverwriteChoice } from "@/entities/media-book";

import {
  axisItems,
  ensureAxisItem,
  findCell,
  mediaBookNameError,
  setCellImage,
  type CellImageResult,
  type MediaBookCellImage,
} from "./mediaBookEdit";
import { MAX_MEDIA_BOOK_CELLS, type MediaBookValues } from "./schema";

/**
 * 파일 이름으로 칸을 한꺼번에 채우는 흐름의 순수 부분. 파일 이름 `인물_장면.확장자` 를 읽고(계획), 사용자가 덮어쓰기
 * 여부를 고른 뒤(확정), 업로드가 끝난 파일마다 폼에 한 장씩 반영한다(적용). 적용을 파일마다 하므로 업로드가 도중에
 * 멈춰도 그때까지 반영된 미디어 북은 그 자체로 완결된 값이다.
 */

// 이미지 파일 확장자. `에리_기쁨.png.webp` 처럼 변환을 거쳐 둘 붙은 것도 모두 뗀다 — 이름 끝의 다른 `.` 은 이름이다.
const IMAGE_EXTENSION = /\.(png|jpe?g|webp|gif)$/i;

export type ParsedMediaFileName =
  | { ok: true; person: string; scene: string }
  | { ok: false; reason: string };

/**
 * 파일 이름을 인물·장면 이름으로 읽는다. 확장자를 떼고 **첫 번째** `_` 에서 나눈다 — 뒤쪽 `_` 는 장면 이름에 남는다
 * (`에리_기쁨_2` → 장면 `기쁨_2`). 나눈 두 이름은 직접 입력과 같은 정규화(앞뒤 공백 제거 + NFC)와 규칙을 거치므로,
 * 맥 Finder 처럼 자모를 나눠(NFD) 보내는 파일 이름도 같은 이름이 된다.
 */
export function parseMediaFileName(fileName: string): ParsedMediaFileName {
  let base = fileName;
  while (IMAGE_EXTENSION.test(base)) base = base.replace(IMAGE_EXTENSION, "");
  const separator = base.indexOf("_");
  if (separator === -1) return { ok: false, reason: "이름에 _ 가 없어 인물과 장면을 나눌 수 없어요" };
  const person = normalizeMediaBookName(base.slice(0, separator));
  const scene = normalizeMediaBookName(base.slice(separator + 1));
  const personError = mediaBookNameError(person, []);
  if (personError !== undefined) return { ok: false, reason: `인물 이름: ${personError}` };
  const sceneError = mediaBookNameError(scene, []);
  if (sceneError !== undefined) return { ok: false, reason: `장면 이름: ${sceneError}` };
  return { ok: true, person, scene };
}

export type BulkUploadEntry = {
  /** 고른 파일 목록에서의 위치. */
  fileIndex: number;
  fileName: string;
  person: string;
  scene: string;
  /** 이미 그림이 있는 칸인가(덮어쓰면 칸 id 는 그대로다). */
  isOverwrite: boolean;
};

export type BulkUploadExclusion = { fileName: string; reason: string };

export type BulkUploadPlan = { entries: BulkUploadEntry[]; excluded: BulkUploadExclusion[] };

/** 파일 이름을 읽어 넣을 칸과 뺄 파일을 가른다. 같은 칸을 가리키는 파일이 둘 이상이면 앞의 것만 넣는다. */
export function planBulkUpload(fileNames: readonly string[], mediaBook: MediaBookValues): BulkUploadPlan {
  const entries: BulkUploadEntry[] = [];
  const excluded: BulkUploadExclusion[] = [];
  const seenPositions = new Set<string>();
  const personIdByName = new Map(mediaBook.people.map((item) => [normalizeMediaBookName(item.name), item.id]));
  const sceneIdByName = new Map(mediaBook.scenes.map((item) => [normalizeMediaBookName(item.name), item.id]));

  fileNames.forEach((fileName, fileIndex) => {
    const parsed = parseMediaFileName(fileName);
    if (!parsed.ok) {
      excluded.push({ fileName, reason: parsed.reason });
      return;
    }
    // 정규화한 이름에는 `/` 가 들어갈 수 없어(이름 규칙) 이어 붙인 키가 서로 다른 자리끼리 겹치지 않는다.
    const position = `${parsed.person}/${parsed.scene}`;
    if (seenPositions.has(position)) {
      excluded.push({ fileName, reason: "같은 칸을 가리키는 파일이 앞에 있어요" });
      return;
    }
    seenPositions.add(position);
    const personId = personIdByName.get(parsed.person);
    const sceneId = sceneIdByName.get(parsed.scene);
    const isOverwrite =
      personId !== undefined && sceneId !== undefined && findCell(mediaBook, personId, sceneId) !== undefined;
    entries.push({ fileIndex, fileName, person: parsed.person, scene: parsed.scene, isOverwrite });
  });

  return { entries, excluded };
}

/**
 * 덮어쓰기 선택을 반영하고 칸 상한을 적용한다. 덮어쓰기는 칸 수를 늘리지 않으므로 상한은 새 칸에만 걸고,
 * 넘치는 새 칸은 파일 순서대로 뒤에서부터 뺀다.
 */
export function finalizeBulkUploadPlan(
  plan: BulkUploadPlan,
  mediaBook: MediaBookValues,
  choice: OverwriteChoice,
): BulkUploadPlan {
  const entries: BulkUploadEntry[] = [];
  const excluded = [...plan.excluded];
  let room = MAX_MEDIA_BOOK_CELLS - mediaBook.cells.length;
  for (const entry of plan.entries) {
    if (entry.isOverwrite) {
      if (choice === "overwrite") entries.push(entry);
      else excluded.push({ fileName: entry.fileName, reason: "이미 그림이 있는 칸이라 건너뛰었어요" });
      continue;
    }
    if (room <= 0) {
      excluded.push({ fileName: entry.fileName, reason: `이미지가 ${MAX_MEDIA_BOOK_CELLS}장을 넘어요` });
      continue;
    }
    room -= 1;
    entries.push(entry);
  }
  return { entries, excluded };
}

/**
 * 이번 일괄 업로드가 이미 아는 축 — 정규화한 이름에서 그 축 id 로. 시작할 때 있던 것과 이번에 만든 것이다. id 를
 * 함께 들고 있어야 아는 이름이 사라졌을 때 "지워졌다"와 "이름이 바뀌었다"(같은 id 가 다른 이름으로 남음)를 가른다.
 */
export type KnownAxisNames = { person: Map<string, string>; scene: Map<string, string> };

export function knownAxisNamesOf(mediaBook: MediaBookValues): KnownAxisNames {
  return {
    person: new Map(mediaBook.people.map((item) => [normalizeMediaBookName(item.name), item.id])),
    scene: new Map(mediaBook.scenes.map((item) => [normalizeMediaBookName(item.name), item.id])),
  };
}

/** 반영에 성공한 파일의 두 이름을 아는 축에 더한다(이번에 만든 축이면 그 id 로). */
export function rememberEntryAxes(
  known: KnownAxisNames,
  mediaBook: MediaBookValues,
  entry: Pick<BulkUploadEntry, "person" | "scene">,
): void {
  const personId = findAxisId(mediaBook, "person", entry.person);
  const sceneId = findAxisId(mediaBook, "scene", entry.scene);
  if (personId !== undefined) known.person.set(entry.person, personId);
  if (sceneId !== undefined) known.scene.set(entry.scene, sceneId);
}

/**
 * 업로드가 끝난 파일 하나를 미디어 북에 반영한다. 없는 인물·장면은 이때 만든다(업로드에 실패한 파일 때문에 빈
 * 축이 생기지 않게). 단 `known` 에 있는데 지금 그 이름이 없으면 사용자가 업로드 도중 손댄 축이라 새로 만들지 않고
 * 거절한다 — 그 축 id 가 다른 이름으로 남아 있으면 `renamed-axis`, 없으면 `missing-axis`(지운 것이 저절로 돌아오거나
 * 옛 이름으로 축이 하나 더 생기면 안 된다). 그사이 상한에 닿았으면 `cap`. 반영에 성공하면 호출부가
 * `rememberEntryAxes` 로 이 파일의 두 이름을 기억한다.
 */
export function applyBulkUploadEntry(
  mediaBook: MediaBookValues,
  entry: Pick<BulkUploadEntry, "person" | "scene">,
  image: MediaBookCellImage,
  createId: () => string,
  known: KnownAxisNames,
): CellImageResult {
  const personTouched = touchedAxis(mediaBook, "person", entry.person, known.person);
  const sceneTouched = touchedAxis(mediaBook, "scene", entry.scene, known.scene);
  if (personTouched === "renamed" || sceneTouched === "renamed") return { ok: false, reason: "renamed-axis" };
  if (personTouched === "removed" || sceneTouched === "removed") return { ok: false, reason: "missing-axis" };
  const withPerson = ensureAxisItem(mediaBook, "person", entry.person, createId);
  const withScene = ensureAxisItem(withPerson.mediaBook, "scene", entry.scene, createId);
  // 상한 때문에 칸을 못 만들면 거절이라, 호출부는 축도 만들지 않은 원래 값을 그대로 둔다.
  return setCellImage(withScene.mediaBook, withPerson.id, withScene.id, image, createId);
}

/** 아는 이름이 지금 미디어 북에 없을 때 무슨 일이 있었는가. 이름이 있거나 처음 보는 이름이면 undefined. */
function touchedAxis(
  mediaBook: MediaBookValues,
  axis: MediaBookAxis,
  name: string,
  known: Map<string, string>,
): "renamed" | "removed" | undefined {
  if (findAxisId(mediaBook, axis, name) !== undefined) return undefined;
  const knownId = known.get(name);
  if (knownId === undefined) return undefined;
  return axisItems(mediaBook, axis).some((item) => item.id === knownId) ? "renamed" : "removed";
}

function findAxisId(mediaBook: MediaBookValues, axis: MediaBookAxis, name: string): string | undefined {
  return axisItems(mediaBook, axis).find((item) => normalizeMediaBookName(item.name) === name)?.id;
}
