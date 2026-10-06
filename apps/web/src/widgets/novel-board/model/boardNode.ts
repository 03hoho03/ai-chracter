import type { Node } from "@xyflow/react";

// 보드 배치 계산이 함께 쓰는 입력·노드 타입과 크기 상수. `@xyflow/react` 에서는 타입만 가져와 배치 계산이 화면 없이
// 테스트되고, 보드 화면을 열지 않는 경로에 캔버스 라이브러리를 끌어오지 않는다.

export type BoardEpisode = { id: string; batchId: string; ordinal: number };
export type BoardBatch = { id: string; ordinal: number };
export type BoardCharacter = { id: string; episodeIds: string[] };

export type BoardModel = {
  batches: BoardBatch[];
  episodes: BoardEpisode[];
  characters: BoardCharacter[];
  hasNotes: boolean;
};

export type BoardPosition = { x: number; y: number };
export type BoardViewport = { x: number; y: number; zoom: number };

export type SavedBoardLayout = {
  version: 1;
  positions: Record<string, BoardPosition>;
  viewport?: BoardViewport;
};

export type EpisodeNodeData = { episodeId: string; batchId: string; ordinal: number };
export type BatchFrameNodeData = { batchId: string; ordinal: number };
export type CharacterNodeData = { characterId: string };
export type NotesNodeData = Record<string, never>;

export type EpisodeNode = Node<EpisodeNodeData, "episode">;
export type BatchFrameNode = Node<BatchFrameNodeData, "batchFrame">;
export type CharacterNode = Node<CharacterNodeData, "character">;
export type NotesNode = Node<NotesNodeData, "notes">;
export type BoardNode = EpisodeNode | BatchFrameNode | CharacterNode | NotesNode;

// 카드 크기와 간격. 노드 컴포넌트는 이 크기로 그려야 묶음 테두리와 인물 레인이 카드와 겹치지 않는다.
// 화를 지그재그로 놓을지는 화면 설계에서 정하므로, 바꿀 때 손댈 곳이 이 숫자들과 화 자리 계산 하나가 되게 모아 둔다.
export const EPISODE_NODE_WIDTH = 240;
export const EPISODE_NODE_HEIGHT = 120;
export const CHARACTER_NODE_WIDTH = 200;
export const CHARACTER_NODE_HEIGHT = 88;
export const NOTES_NODE_WIDTH = 200;
export const NOTES_NODE_HEIGHT = 120;
/** 같은 묶음 안 화 사이 간격. */
export const EPISODE_GAP = 24;
/** 묶음 사이 간격. 두 묶음 테두리의 여백과 머리 줄을 더한 것보다 넓어야 이웃 테두리가 겹치지 않는다. */
export const BATCH_GAP = 72;
/** 화 열과 인물 레인 사이, 설정 노트와 화 열 사이 간격. */
export const LANE_GAP = 120;
/** 같은 높이에 처음 나온 인물들이 겹치지 않게 아래로 밀 때의 간격. */
export const CHARACTER_GAP = 16;
/** 묶음 테두리가 구성 화 카드 바깥으로 두르는 여백. */
export const BATCH_FRAME_PADDING = 16;
/** 묶음 테두리 위쪽에 묶음 이름을 적을 머리 줄 높이(여백에 더한다). */
export const BATCH_FRAME_LABEL_HEIGHT = 24;

// 노드 키는 서버에 저장되는 배치의 키와 같은 문자열이다 — 저장값을 노드에 다시 붙이는 유일한 연결 고리다.
export const NOTES_NODE_KEY = "notes";
export function episodeNodeKey(episodeId: string): string {
  return `episode:${episodeId}`;
}
export function characterNodeKey(characterId: string): string {
  return `character:${characterId}`;
}
/** 묶음 테두리는 저장하지 않는 파생 노드라, 저장 키와 겹치지 않는 접두사를 쓴다. */
export function batchFrameNodeKey(batchId: string): string {
  return `batch:${batchId}`;
}
