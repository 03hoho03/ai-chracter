import { findCell } from "./mediaBookEdit";
import { MAX_MEDIA_BOOK_CELLS, type MediaBookCellValues, type MediaBookValues } from "./schema";

type CellPosition = { personId: string; sceneId: string };

/**
 * 이미지 → 그 이미지를 쓰는 다른 칸들을 말하는 한 구절(`도희 · 진심, 유나 · 리딩 칸에 씀`). 생성 이미지 고르기에서
 * 이미 다른 칸에 넣은 이미지를 알아보게 한다. 서버 기록이 아니라 지금 폼에서 만들므로 저장 전 초안도 반영되고,
 * 채우려는 칸 자신은 뺀다. 칸은 표 순서(장면 → 인물)로 늘어놓는다.
 */
export function toUsedAssetLabels(mediaBook: MediaBookValues, picking: CellPosition): Map<string, string> {
  const namesByAsset = new Map<string, string[]>();
  for (const scene of mediaBook.scenes) {
    for (const person of mediaBook.people) {
      if (person.id === picking.personId && scene.id === picking.sceneId) continue;
      const cell = findCell(mediaBook, person.id, scene.id);
      if (!cell) continue;
      const names = namesByAsset.get(cell.imageAssetId) ?? [];
      names.push(`${person.name} · ${scene.name}`);
      namesByAsset.set(cell.imageAssetId, names);
    }
  }
  return new Map([...namesByAsset].map(([assetId, names]) => [assetId, `${names.join(", ")} 칸에 씀`]));
}

/** 표 위 진척 한 줄과 "다음 미완성 칸" 이 같은 셈을 쓰도록 둘 다 여기서 센다. */
export type MediaBookProgress = {
  /** 인물 × 장면 — 표의 칸 수. */
  totalCells: number;
  /** 이미지가 든 칸 수. */
  filledCells: number;
  /** 이미지는 있는데 상황 설명이 공백뿐인 칸 수. */
  missingDescriptionCells: number;
  /** 표의 칸이 이미지 상한보다 많아 끝까지 채울 수 없는가. */
  isOverCellLimit: boolean;
};

/** 해금 힌트는 비워도 되는 값이라 세지 않는다 — 이미지와 상황 설명(AI가 이미지를 고를 때 읽는 글)만 본다. */
function hasDescription(cell: MediaBookCellValues): boolean {
  return cell.situationDescription.trim() !== "";
}

export function summarizeMediaBookProgress(mediaBook: MediaBookValues): MediaBookProgress {
  let filledCells = 0;
  let missingDescriptionCells = 0;
  for (const scene of mediaBook.scenes) {
    for (const person of mediaBook.people) {
      const cell = findCell(mediaBook, person.id, scene.id);
      if (!cell) continue;
      filledCells += 1;
      if (!hasDescription(cell)) missingDescriptionCells += 1;
    }
  }
  const totalCells = mediaBook.people.length * mediaBook.scenes.length;
  return { totalCells, filledCells, missingDescriptionCells, isOverCellLimit: totalCells > MAX_MEDIA_BOOK_CELLS };
}

/** 진척 한 줄(`21칸 중 3칸 채움 · 상황 설명 없는 칸 2`). 0 인 덧붙임은 뺀다. */
export function formatMediaBookProgress(progress: MediaBookProgress): string {
  const { totalCells, filledCells, missingDescriptionCells, isOverCellLimit } = progress;
  if (filledCells === totalCells && missingDescriptionCells === 0) return `${totalCells}칸 모두 채움`;
  const parts = [`${totalCells}칸 중 ${filledCells}칸 채움`];
  if (missingDescriptionCells > 0) parts.push(`상황 설명 없는 칸 ${missingDescriptionCells}`);
  if (isOverCellLimit) parts.push(`이미지는 ${MAX_MEDIA_BOOK_CELLS}칸까지 넣을 수 있어요`);
  return parts.join(" · ");
}

/**
 * 지금 칸 다음의 미완성 칸 — 이미지가 없거나 상황 설명이 공백뿐인 칸. 표를 읽는 순서(장면 줄 → 그 줄의 인물)로
 * 지금 칸 다음부터 찾고, 끝에 닿으면 처음으로 돈다. 지금 칸은 돌려주지 않는다. 이미지가 상한만큼 찼으면 빈 칸은 더
 * 채울 수 없으므로 건너뛰고 설명 없는 칸만 찾는다.
 */
export function findNextIncompleteCell(
  mediaBook: MediaBookValues,
  current: CellPosition,
): CellPosition | undefined {
  const canAddImage = mediaBook.cells.length < MAX_MEDIA_BOOK_CELLS;
  const positions = mediaBook.scenes.flatMap((scene) =>
    mediaBook.people.map((person) => ({ personId: person.id, sceneId: scene.id })),
  );
  const currentIndex = positions.findIndex(
    (position) => position.personId === current.personId && position.sceneId === current.sceneId,
  );
  for (let step = 1; step <= positions.length; step += 1) {
    const position = positions[(currentIndex + step + positions.length) % positions.length];
    if (!position || (position.personId === current.personId && position.sceneId === current.sceneId)) continue;
    const cell = findCell(mediaBook, position.personId, position.sceneId);
    if (cell ? !hasDescription(cell) : canAddImage) return position;
  }
  return undefined;
}
