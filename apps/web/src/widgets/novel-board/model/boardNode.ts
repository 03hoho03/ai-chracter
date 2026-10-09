import type { Node } from "@xyflow/react";

import type { NovelBatchSummary, NovelChapterSummary, NovelCharacterResponse } from "@/entities/novel";

// 보드 배치 계산이 함께 쓰는 입력·노드 타입과 크기 상수. `@xyflow/react` 에서는 타입만 가져와 배치 계산이 화면 없이
// 테스트되고, 보드 화면을 열지 않는 경로에 캔버스 라이브러리를 끌어오지 않는다.
//
// 입력 타입은 응답 타입에서 칸을 골라 만든다 — 사본 타입을 따로 두면 서버 칸 이름이 바뀌어도 typecheck 가 잡지 못한다
// (인물의 나온 화가 `chapterIds` 인데 사본이 `episodeIds` 였던 일이 있었다).

/** 화 카드가 읽는 진행. 다 읽은 화, 읽던 자리가 있는 화(그 자리까지의 비율), 연 적 없는 화. */
export type EpisodeReadState = { kind: "finished" } | { kind: "reading"; percent: number } | { kind: "unread" };

export type BoardEpisode = Pick<NovelChapterSummary, "id" | "batchId" | "ordinal" | "title" | "summary" | "charCount"> & {
  readState: EpisodeReadState;
  /** 적용하지 않은 AI 수정안이 있는가. */
  hasPendingAiEdit: boolean;
  /** 이 화가 든 묶음을 다시 만드는 중인가. */
  isRegenerating: boolean;
};
export type BoardBatch = Pick<NovelBatchSummary, "id" | "ordinal"> & {
  /** 묶음에 든 화 범위(`3~5화`). 화가 없는 묶음(낡은 상세)은 `undefined`. */
  rangeLabel: string | undefined;
};
export type BoardCharacter = Pick<NovelCharacterResponse, "id" | "name" | "aliases" | "memo" | "chapterIds">;

export type BoardModel = {
  batches: BoardBatch[];
  episodes: BoardEpisode[];
  characters: BoardCharacter[];
  /** 설정 노트 전문(비었으면 `""`). 노트 카드는 비어 있어도 그린다 — 캔버스에서 노트를 쓰는 입구라서. */
  notes: string;
};

export type BoardPosition = { x: number; y: number };

// 노드 `data` 에는 카드가 그릴 칸을 직접 싣는다. 노드 컴포넌트는 `memo` 라 `data` 가 바뀌어야 다시 그려진다 — 조회
// 표를 컨텍스트로 넘기면 제목을 고쳐도 카드가 그대로다.
export type EpisodeNodeData = Omit<BoardEpisode, "id"> & { episodeId: string };
export type BatchFrameNodeData = { batchId: string; ordinal: number; rangeLabel: string | undefined };
export type CharacterNodeData = {
  characterId: string;
  name: string;
  memo: string;
  /** 보드에 지금 있는 화 가운데 이 인물이 나온 화 수. */
  appearanceCount: number;
};
export type NotesNodeData = { notes: string };

export type EpisodeNode = Node<EpisodeNodeData, "episode">;
export type BatchFrameNode = Node<BatchFrameNodeData, "batchFrame">;
export type CharacterNode = Node<CharacterNodeData, "character">;
export type NotesNode = Node<NotesNodeData, "notes">;
export type BoardNode = EpisodeNode | BatchFrameNode | CharacterNode | NotesNode;

// 카드 크기와 간격. 노드 컴포넌트는 이 크기로 그려야 묶음 테두리와 인물 레인이 카드와 겹치지 않는다.
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

// 선이 카드의 어느 변에 꽂히나. 화 카드에는 들어오는 선이 두 종류라(위: 앞 화, 오른쪽: 인물) 핸들이 하나면 인물 선이
// 카드 위쪽에 꽂힌다. 선과 노드 컴포넌트의 `Handle` 이 같은 id 를 써야 이어진다.
/** 화 카드 아래 — 다음 화로 나가는 선. */
export const NEXT_SOURCE_HANDLE = "next-out";
/** 화 카드 위 — 앞 화에서 들어오는 선. */
export const NEXT_TARGET_HANDLE = "next-in";
/** 인물 카드 왼쪽 — 나온 화로 나가는 선. */
export const APPEARS_SOURCE_HANDLE = "appears-out";
/** 화 카드 오른쪽 — 인물에서 들어오는 선. */
export const APPEARS_TARGET_HANDLE = "appears-in";

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
