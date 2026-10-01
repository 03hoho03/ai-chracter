import type { components } from "@ai-character-chat/api-types";

import type { MediaTagImages } from "../model/mediaTags";

type MediaTagImageDto = components["schemas"]["MediaTagImage"];

/** REST 응답의 그림 맵을 앱 모양으로 옮긴다 — 서버의 null 크기를 비운 값으로 접는다. 맵이 없으면 빈 맵. */
export function toMediaTagImages(dto: Record<string, MediaTagImageDto> | undefined): MediaTagImages {
  return Object.fromEntries(
    Object.entries(dto ?? {}).map(([cellId, image]) => [
      cellId,
      { url: image.url, width: image.width ?? undefined, height: image.height ?? undefined },
    ]),
  );
}
