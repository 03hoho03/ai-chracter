import { findCell } from "./mediaBookEdit";
import type { MediaBookValues } from "./schema";

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
