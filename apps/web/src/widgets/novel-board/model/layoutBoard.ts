import type { Edge } from "@xyflow/react";

import type { NovelBoardLayout } from "@/entities/novel";

import {
  APPEARS_SOURCE_HANDLE,
  APPEARS_TARGET_HANDLE,
  BATCH_GAP,
  CHARACTER_GAP,
  CHARACTER_NODE_HEIGHT,
  EPISODE_GAP,
  EPISODE_NODE_HEIGHT,
  EPISODE_NODE_WIDTH,
  LANE_GAP,
  NEXT_SOURCE_HANDLE,
  NEXT_TARGET_HANDLE,
  NOTES_NODE_KEY,
  NOTES_NODE_WIDTH,
  characterNodeKey,
  episodeNodeKey,
  type BoardCharacter,
  type BoardEpisode,
  type BoardModel,
  type BoardNode,
  type BoardPosition,
  type CharacterNode,
  type EpisodeNode,
  type NotesNode,
} from "./boardNode";
import { fitBatchFrames } from "./fitBatchFrames";

const EPISODE_COLUMN_X = 0;
const CHARACTER_LANE_X = EPISODE_COLUMN_X + EPISODE_NODE_WIDTH + LANE_GAP;
const NOTES_POSITION: BoardPosition = { x: EPISODE_COLUMN_X - LANE_GAP - NOTES_NODE_WIDTH, y: 0 };

function compareIds(a: string, b: string): number {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/** 화를 놓는 순서 — 묶음 순서, 같은 묶음 안에서는 화 번호. 목록에 없는 묶음의 화는 맨 뒤로 보낸다. */
function sortEpisodes(model: BoardModel): BoardEpisode[] {
  const batchOrdinal = new Map(model.batches.map((batch) => [batch.id, batch.ordinal]));
  const orderOf = (episode: BoardEpisode) => batchOrdinal.get(episode.batchId) ?? Number.POSITIVE_INFINITY;
  return [...model.episodes].sort(
    (a, b) => orderOf(a) - orderOf(b) || a.ordinal - b.ordinal || compareIds(a.id, b.id),
  );
}

/** 자동 배치 — 화는 세로 한 열, 묶음이 바뀌면 간격을 더 둔다. 결과는 정렬된 화와 같은 순서다. */
function placeEpisodes(episodes: BoardEpisode[]): BoardPosition[] {
  const positions: BoardPosition[] = [];
  let y = 0;
  let previousBatchId: string | undefined;
  for (const episode of episodes) {
    if (previousBatchId !== undefined) {
      y += EPISODE_NODE_HEIGHT + (episode.batchId === previousBatchId ? EPISODE_GAP : BATCH_GAP);
    }
    positions.push({ x: EPISODE_COLUMN_X, y });
    previousBatchId = episode.batchId;
  }
  return positions;
}

/** 인물은 오른쪽 레인에서 처음 나온 화의 높이에 둔다. 같은 높이에 몰리면 앞 인물 아래로 민다.
 * 나온 화가 보드에 하나도 없는 인물은 나온 인물들 뒤에 쌓는다. */
function firstAppearanceIndex(character: BoardCharacter, episodeIndex: Map<string, number>): number {
  return Math.min(
    Number.POSITIVE_INFINITY,
    ...character.chapterIds.map((chapterId) => episodeIndex.get(chapterId) ?? Number.POSITIVE_INFINITY),
  );
}

function placeCharacters(
  characters: BoardCharacter[],
  episodes: BoardEpisode[],
  episodePositions: BoardPosition[],
): { character: BoardCharacter; position: BoardPosition }[] {
  const episodeIndex = new Map(episodes.map((episode, index) => [episode.id, index]));
  const sorted = characters
    .map((character) => ({ character, first: firstAppearanceIndex(character, episodeIndex) }))
    .sort((a, b) => a.first - b.first || compareIds(a.character.id, b.character.id));

  let nextFreeY = Number.NEGATIVE_INFINITY;
  return sorted.map(({ character, first }) => {
    const anchorY = episodePositions[first]?.y ?? 0;
    const y = Math.max(anchorY, nextFreeY);
    nextFreeY = y + CHARACTER_NODE_HEIGHT + CHARACTER_GAP;
    return { character, position: { x: CHARACTER_LANE_X, y } };
  });
}

/** 저장된 위치가 있으면 그것을, 없으면 자동 위치를 쓴다. 지금 보드에 없는 대상의 저장 키는 아예 읽지 않는다. */
function resolvePosition(key: string, auto: BoardPosition, saved: NovelBoardLayout | null | undefined): BoardPosition {
  const stored = saved?.positions[key];
  return stored ? { x: stored.x, y: stored.y } : auto;
}

// 선의 접근 이름과 역할 설명. 라이브러리는 이름이 없으면 영어(`Edge from <키> to <키>`)를, 역할 설명은 늘 영어
// "edge" 를 단다 — 선마다 한국어로 덮는다.
const EDGE_ROLE_DESCRIPTION = { "aria-roledescription": "선" };

/** 화 → 다음 화 선. 화 순서를 보여 주는 고정 선이라 사용자가 잇거나 끊지 않는다. */
function buildNextEpisodeEdges(episodes: BoardEpisode[]): Edge[] {
  return episodes.slice(1).flatMap((current, index) => {
    const previous = episodes[index];
    if (!previous) return [];
    return [
      {
        id: `next:${previous.id}:${current.id}`,
        source: episodeNodeKey(previous.id),
        target: episodeNodeKey(current.id),
        sourceHandle: NEXT_SOURCE_HANDLE,
        targetHandle: NEXT_TARGET_HANDLE,
        ariaLabel: `${previous.ordinal}화 → ${current.ordinal}화`,
        domAttributes: EDGE_ROLE_DESCRIPTION,
      },
    ];
  });
}

/**
 * 보드의 노드와 선을 계산한다. 같은 입력이면 언제나 같은 출력이다 — 입력 배열 순서와 무관하게 화는 묶음·화 순서로,
 * 인물은 첫 등장 순서로 정렬한다. 저장된 위치는 그 노드의 자동 위치를 이긴다. 저장한 적이 없거나 배치를 받지
 * 못했으면(`null`·`undefined`) 전부 자동 위치다.
 * 묶음 테두리는 저장하지 않는 파생 노드라 위치를 정한 뒤 구성 화의 경계 상자로 계산한다.
 *
 * 노드 배열 순서는 노트 → 화(읽는 순서) → 인물(첫 등장 순서)이다. 캔버스의 Tab 순서가 이 순서라 읽는 순서와 같다.
 */
export function layoutBoard(
  model: BoardModel,
  saved: NovelBoardLayout | null | undefined,
): { nodes: BoardNode[]; edges: Edge[] } {
  const episodes = sortEpisodes(model);
  const autoEpisodePositions = placeEpisodes(episodes);

  const episodeNodes: EpisodeNode[] = episodes.map(({ id, ...display }, index) => ({
    id: episodeNodeKey(id),
    type: "episode",
    position: resolvePosition(episodeNodeKey(id), autoEpisodePositions[index] ?? { x: EPISODE_COLUMN_X, y: 0 }, saved),
    data: { episodeId: id, ...display },
  }));
  const liveEpisodeIds = new Set(episodes.map((episode) => episode.id));

  // 인물의 자동 높이는 화의 **자동** 위치를 따른다. 옮긴 화를 따라가게 하면 화 하나를 옮길 때마다 사용자가 둔 적
  // 없는 인물 카드까지 함께 움직여, 새로고침마다 레인이 흐트러진다.
  const characterNodes: CharacterNode[] = placeCharacters(model.characters, episodes, autoEpisodePositions).map(
    ({ character, position }) => ({
      id: characterNodeKey(character.id),
      type: "character",
      position: resolvePosition(characterNodeKey(character.id), position, saved),
      data: {
        characterId: character.id,
        name: character.name,
        memo: character.memo,
        appearanceCount: character.chapterIds.filter((chapterId) => liveEpisodeIds.has(chapterId)).length,
      },
    }),
  );

  const notesNode: NotesNode = {
    id: NOTES_NODE_KEY,
    type: "notes",
    position: resolvePosition(NOTES_NODE_KEY, NOTES_POSITION, saved),
    data: { notes: model.notes },
  };

  const nodes = fitBatchFrames([notesNode, ...episodeNodes, ...characterNodes], model);
  return { nodes, edges: buildNextEpisodeEdges(episodes) };
}

/** 고르거나 포커스한 인물과 그 인물이 나온 화를 잇는 선. 모든 인물의 선을 늘 그리면 읽을 수 없어 한 인물만 그린다. */
export function buildCharacterEdges(characterId: string | undefined, model: BoardModel): Edge[] {
  if (characterId === undefined) return [];
  const character = model.characters.find((candidate) => candidate.id === characterId);
  if (!character) return [];
  const ordinalById = new Map(model.episodes.map((episode) => [episode.id, episode.ordinal]));
  return character.chapterIds
    .filter((chapterId) => ordinalById.has(chapterId))
    .map((chapterId) => ({
      id: `appears:${character.id}:${chapterId}`,
      source: characterNodeKey(character.id),
      target: episodeNodeKey(chapterId),
      sourceHandle: APPEARS_SOURCE_HANDLE,
      targetHandle: APPEARS_TARGET_HANDLE,
      ariaLabel: `인물 ${character.name} · ${ordinalById.get(chapterId)}화`,
      domAttributes: EDGE_ROLE_DESCRIPTION,
    }));
}
