import type { BoardBatch, BoardCharacter, BoardEpisode, BoardModel } from "./boardNode";

// 배치 테스트들이 함께 쓰는 입력 만들기. 표시 칸은 배치 계산과 무관해 기본값으로 채운다.

export function testBatch(id: string, ordinal: number): BoardBatch {
  return { id, ordinal, rangeLabel: `${ordinal}화` };
}

export function testEpisode(id: string, batchId: string, ordinal: number): BoardEpisode {
  return {
    id,
    batchId,
    ordinal,
    title: null,
    summary: null,
    charCount: 0,
    readState: { kind: "unread" },
    hasPendingAiEdit: false,
    isRegenerating: false,
  };
}

export function testCharacter(id: string, chapterIds: string[]): BoardCharacter {
  return { id, name: id, aliases: [], memo: "", chapterIds };
}

export function testModel(parts: Partial<BoardModel>): BoardModel {
  return { batches: [], episodes: [], characters: [], notes: "", ...parts };
}
