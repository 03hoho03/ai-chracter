import { describe, expect, it } from "vitest";

import { toChatRoomMemoryItemsPage } from "./toChatRoomMemoryItems";

const EPISODE = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "편의점 야간 근무 첫날",
  detail: "새벽 두 시, 우산 없이 들어온 손님이 따뜻한 캔커피를 샀다.",
  assertedBy: "mixed" as const,
  startTurn: 1,
  endTurn: 3,
};

const RELATION = {
  id: "22222222-2222-4222-8222-222222222222",
  factKey: "relation:점장:서아",
  kind: "relation" as const,
  subject: "점장",
  object: "서아",
  attribute: null,
  value: "먼 친척",
  truthStatus: "claimed" as const,
  truthLabel: "누군가의 말",
  assertedBy: "character" as const,
  speaker: "손님",
  startTurn: 37,
  endTurn: 38,
};

const FACT = {
  id: "33333333-3333-4333-8333-333333333333",
  factKey: "fact:지호:사는 곳",
  kind: "fact" as const,
  subject: "지호",
  object: null,
  attribute: "사는 곳",
  value: "편의점 건너편 원룸",
  truthStatus: "confirmed" as const,
  truthLabel: "이야기 속 사실",
  assertedBy: "narration" as const,
  speaker: null,
  startTurn: 2,
  endTurn: 2,
};

describe("toChatRoomMemoryItemsPage", () => {
  it("turns the server's nulls into missing values and keeps everything else", () => {
    const page = toChatRoomMemoryItemsPage({
      episodes: [EPISODE],
      nextCursor: null,
      facts: [RELATION, FACT],
      episodesUsedInReplies: true,
      factsUsedInReplies: false,
      impressions: null,
    });
    expect(page).toEqual({
      episodes: [EPISODE],
      nextCursor: undefined,
      facts: [
        { ...RELATION, attribute: undefined },
        { ...FACT, object: undefined, speaker: undefined },
      ],
      episodesUsedInReplies: true,
      factsUsedInReplies: false,
    });
  });

  it("keeps the cursor for the next page", () => {
    const page = toChatRoomMemoryItemsPage({
      episodes: [],
      nextCursor: "cursor-2",
      facts: [],
      episodesUsedInReplies: false,
      factsUsedInReplies: false,
      impressions: null,
    });
    expect(page.nextCursor).toBe("cursor-2");
  });
});
