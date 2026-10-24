/** 장면 기억 하나. `assertedBy`는 장면 내용을 누가 말했는가다 — `character`(캐릭터가 대사로만 말한 장면)는 응답에서
 * 다시 떠올리지 않는다. 턴은 추출 시점의 응답 순번이라 그 뒤 메시지가 지워졌으면 근사값이다. */
export type ChatRoomMemoryEpisode = {
  id: string;
  title: string;
  detail: string;
  assertedBy: "user" | "character" | "narration" | "mixed";
  startTurn: number;
  endTurn: number;
};

/** 키마다 지금 이긴 사실 하나. `relation`이면 `subject`와 `object` 사이 관계, `fact`면 `subject`의 `attribute`다.
 * `truthLabel`은 서버가 사용자에게 보일 말로 바꾼 진실 상태이고, `speaker`는 그 말을 한 인물이다(없으면 없다). */
export type ChatRoomMemoryFact = {
  id: string;
  factKey: string;
  kind: "relation" | "fact";
  subject: string;
  object?: string;
  attribute?: string;
  value: string;
  truthStatus: "confirmed" | "claimed" | "disproved";
  truthLabel: string;
  assertedBy: "user" | "character" | "narration";
  speaker?: string;
  startTurn: number;
  endTurn: number;
};

/** 목록 API 한 페이지. 장면만 페이지로 나뉘고, 사실과 두 쓰임 표시는 페이지마다 같은 것이 다시 온다. */
export type ChatRoomMemoryItemsPage = {
  episodes: ChatRoomMemoryEpisode[];
  nextCursor?: string;
  facts: ChatRoomMemoryFact[];
  episodesUsedInReplies: boolean;
  factsUsedInReplies: boolean;
};

/** 화면이 그리는 모양 — 불러온 장면 전부와 가장 최근에 받은 사실·쓰임 표시. */
export type ChatRoomMemoryItems = {
  episodes: ChatRoomMemoryEpisode[];
  facts: ChatRoomMemoryFact[];
  hasMoreEpisodes: boolean;
  episodesUsedInReplies: boolean;
  factsUsedInReplies: boolean;
};

/** 불러온 페이지들을 한 목록으로 합친다. 사실과 쓰임 표시는 마지막 페이지의 것을 쓴다 — 모든 페이지가 같은 것을 다시 싣고,
 * 마지막 페이지가 가장 늦게 받은 값이다. */
export function mergeMemoryItemPages(pages: readonly ChatRoomMemoryItemsPage[]): ChatRoomMemoryItems {
  const last = pages.at(-1);
  return {
    episodes: pages.flatMap((page) => page.episodes),
    facts: last?.facts ?? [],
    hasMoreEpisodes: last?.nextCursor !== undefined,
    episodesUsedInReplies: last?.episodesUsedInReplies ?? false,
    factsUsedInReplies: last?.factsUsedInReplies ?? false,
  };
}
