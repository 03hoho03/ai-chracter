import type { BoardModel, CharacterNodeData, EpisodeNodeData } from "./boardNode";

/** 좁은 화면 흐름 목록의 화 탭 한 덩어리 — 묶음 하나와 그 화들. */
export type FlowListSection = { key: string; label: string; episodes: EpisodeNodeData[] };

function compareIds(a: string, b: string): number {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/** 화 탭 — 묶음 번호 순, 묶음 안은 화 번호 순. 캔버스의 화 열과 같은 순서다. 목록에 없는 묶음의 화(낡은 상세)는 머리
 * 없이 맨 뒤 덩어리로 모은다. 화가 없는 묶음은 덩어리를 만들지 않는다. */
export function toFlowListSections(model: BoardModel): FlowListSection[] {
  const byBatch = new Map<string, EpisodeNodeData[]>();
  for (const { id, ...display } of [...model.episodes].sort((a, b) => a.ordinal - b.ordinal || compareIds(a.id, b.id))) {
    const list = byBatch.get(display.batchId) ?? [];
    list.push({ episodeId: id, ...display });
    byBatch.set(display.batchId, list);
  }
  const sections: FlowListSection[] = [];
  for (const batch of [...model.batches].sort((a, b) => a.ordinal - b.ordinal)) {
    const episodes = byBatch.get(batch.id);
    if (episodes === undefined) continue;
    byBatch.delete(batch.id);
    sections.push({
      key: batch.id,
      label: batch.rangeLabel === undefined ? `묶음 ${batch.ordinal}` : `묶음 ${batch.ordinal} · ${batch.rangeLabel}`,
      episodes,
    });
  }
  const orphans = [...byBatch.values()].flat();
  if (orphans.length > 0) sections.push({ key: "orphans", label: "묶음 정보 없음", episodes: orphans });
  return sections;
}

/** 인물 탭 — 처음 나온 화 순(캔버스 인물 레인과 같은 순서), 나온 화가 지금 없으면 뒤로. 나온 화 수는 지금 있는 화만 센다. */
export function toFlowListCharacters(model: BoardModel): CharacterNodeData[] {
  const ordinalById = new Map(model.episodes.map((episode) => [episode.id, episode.ordinal]));
  return model.characters
    .map((character) => {
      const appeared = character.chapterIds.flatMap((chapterId) => {
        const ordinal = ordinalById.get(chapterId);
        return ordinal === undefined ? [] : [ordinal];
      });
      return { character, first: Math.min(Number.POSITIVE_INFINITY, ...appeared), count: appeared.length };
    })
    .sort((a, b) => a.first - b.first || compareIds(a.character.id, b.character.id))
    .map(({ character, count }) => ({
      characterId: character.id,
      name: character.name,
      memo: character.memo,
      appearanceCount: count,
    }));
}
