import type { MediaTagImages } from "@/entities/media-book";

import type { MediaBookCellValues } from "./schema";

type CellImageSize = { width?: number; height?: number };

/**
 * 대화 미리보기 첫 메시지에 그릴 칸 그림 맵(`{칸 id: 그림}`)을 빌더가 이미 가진 값으로 만든다 — 미리보기 화면은 세션이
 * 생기기 전에도 그려지므로 서버에 묻지 않는다.
 * - 주소는 `resolveUrl`(빌더 칸 썸네일 주소 — 같은 자산이면 이미 쓰던 주소, 방금 올린 파일이면 로컬 주소)이 준다.
 *   주소가 없는 칸은 그릴 수 없어 뺀다(태그는 빈칸이 된다).
 * - 크기는 폼 값이 먼저, 없으면 최근 저장 응답의 같은 자산 값(`sizeByAssetId`)이다. 이 기기에서 방금 올린 그림은 저장
 *   응답이 오기 전까지 크기를 몰라 고정 웰로 그려진다.
 */
export function toMediaBookPreviewImages(
  cells: readonly MediaBookCellValues[],
  resolveUrl: (assetId: string, fallbackUrl?: string) => string | undefined,
  sizeByAssetId: ReadonlyMap<string, CellImageSize>,
): MediaTagImages {
  return Object.fromEntries(
    cells.flatMap((cell) => {
      const url = resolveUrl(cell.imageAssetId, cell.imageUrl);
      if (url === undefined) return [];
      const saved = sizeByAssetId.get(cell.imageAssetId);
      const width = cell.imageWidth ?? saved?.width;
      const height = cell.imageHeight ?? saved?.height;
      return [[cell.id.toLowerCase(), { url, width, height }]];
    }),
  );
}
