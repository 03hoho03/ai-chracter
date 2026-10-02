import { isApiError } from "@/shared/api/client";

import type { MediaBookValues } from "./schema";

// 발행이 칸 그림의 블러본을 만들다 실패했을 때 서버가 돌려주는 502 의 `detail.code`. 응답에 실리는 실제 식별자다.
const IMAGE_UNAVAILABLE_CODE = "MEDIA_BOOK_IMAGE_UNAVAILABLE";

/**
 * 발행이 미디어 북 칸 그림을 처리하지 못한 경우의 안내. 그 밖의 실패면 undefined(기본 문구).
 *
 * 서버가 실패한 칸의 id 를 주므로, 폼에 그 칸이 있으면 인물 × 장면 이름으로 짚어 준다 — 칸이 많을 때 어느 그림을
 * 다시 올려야 하는지 사용자가 찾지 않아도 된다. 그림 저장소가 잠깐 실패한 경우도 같은 응답이라 다시 발행하라는
 * 안내를 함께 둔다.
 */
export function mediaBookPublishErrorMessage(error: unknown, mediaBook: MediaBookValues): string | undefined {
  if (!isApiError(error) || error.status !== 502) return undefined;
  if (typeof error.detail !== "object" || error.detail.code !== IMAGE_UNAVAILABLE_CODE) return undefined;

  const cellLabel = findCellLabel(mediaBook, error.detail.cellId);
  const subject = cellLabel ? `미디어 북 '${cellLabel}' 칸의 이미지를` : "미디어 북 칸 이미지 하나를";
  return `${subject} 처리하지 못해 발행이 멈췄어요. 잠시 뒤 다시 발행하고, 같은 일이 반복되면 그 칸 이미지를 다시 올려 주세요.`;
}

function findCellLabel(mediaBook: MediaBookValues, cellId: unknown): string | undefined {
  if (typeof cellId !== "string") return undefined;
  const cell = mediaBook.cells.find((candidate) => candidate.id === cellId);
  if (cell === undefined) return undefined;
  const person = mediaBook.people.find((item) => item.id === cell.personId);
  const scene = mediaBook.scenes.find((item) => item.id === cell.sceneId);
  if (person === undefined || scene === undefined) return undefined;
  return `${person.name} / ${scene.name}`;
}
