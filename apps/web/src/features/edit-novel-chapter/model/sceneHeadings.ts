import type { NovelRevisionScene } from "@/entities/novel";

import { toSceneKey } from "./blockSelection";

/** 장면 머리줄 하나. `sceneKey` 는 고르기의 장면 열쇠(`toSceneKeyOf`)와 같은 값이라 고른 장면과 견줄 수 있다. */
export type SceneHeading = { sceneKey: string; label: string };

/** 장면 경계가 있는 화(구성안으로 쓴 화)의 머리줄 — 문단 인덱스 → 그 자리에서 시작하는 장면. 장면마다 지금 판에서 가장 앞선
 * 블록 자리에 한 번 서고, 번호는 본문 차례로 매긴다. 경계가 없는 화와 블록이 지금 판에 하나도 없는 장면에는 머리줄이 없다. */
export function toSceneHeadings(revision: {
  blocks: readonly { id: string }[];
  scenes: readonly NovelRevisionScene[];
}): Map<number, SceneHeading> {
  const position = new Map(revision.blocks.map((block, index) => [block.id, index]));
  const starts = revision.scenes
    .map((scene) => {
      const indexes = scene.blockIds.map((id) => position.get(id)).filter((index) => index !== undefined);
      return { scene, start: indexes.length === 0 ? undefined : Math.min(...indexes) };
    })
    .filter((item): item is { scene: NovelRevisionScene; start: number } => item.start !== undefined)
    .sort((a, b) => a.start - b.start);
  return new Map(
    starts.map(({ scene, start }, rank) => {
      const title = scene.title.trim();
      return [start, { sceneKey: toSceneKey(scene.id), label: `장면 ${rank + 1}${title === "" ? "" : ` · ${title}`}` }];
    }),
  );
}
