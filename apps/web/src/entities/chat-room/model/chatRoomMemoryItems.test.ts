import { describe, expect, it } from "vitest";

import { mergeMemoryItemPages, type ChatRoomMemoryItemsPage } from "./chatRoomMemoryItems";

function episode(id: string) {
  return { id, title: `장면 ${id}`, detail: "", assertedBy: "narration" as const, startTurn: 1, endTurn: 2 };
}

function fact(id: string) {
  return {
    id,
    factKey: `fact:${id}`,
    kind: "fact" as const,
    subject: "서아",
    attribute: id,
    value: "값",
    truthStatus: "confirmed" as const,
    truthLabel: "이야기 속 사실",
    assertedBy: "narration" as const,
    startTurn: 1,
    endTurn: 1,
  };
}

function page(overrides: Partial<ChatRoomMemoryItemsPage>): ChatRoomMemoryItemsPage {
  return {
    episodes: [],
    facts: [],
    episodesUsedInReplies: false,
    factsUsedInReplies: false,
    ...overrides,
  };
}

describe("mergeMemoryItemPages", () => {
  it("joins the scene pages in order", () => {
    const merged = mergeMemoryItemPages([
      page({ episodes: [episode("a"), episode("b")], nextCursor: "c1" }),
      page({ episodes: [episode("c")] }),
    ]);
    expect(merged.episodes.map((item) => item.id)).toEqual(["a", "b", "c"]);
  });

  it("says more scenes remain only while the last page carries a cursor", () => {
    expect(mergeMemoryItemPages([page({ nextCursor: "c1" })]).hasMoreEpisodes).toBe(true);
    expect(mergeMemoryItemPages([page({ nextCursor: "c1" }), page({})]).hasMoreEpisodes).toBe(false);
  });

  it("takes the facts and the reply-use flags from the newest page, because every page repeats them", () => {
    const merged = mergeMemoryItemPages([
      page({ facts: [fact("old")], nextCursor: "c1", episodesUsedInReplies: false, factsUsedInReplies: false }),
      page({ facts: [fact("new")], episodesUsedInReplies: true, factsUsedInReplies: true }),
    ]);
    expect(merged.facts.map((item) => item.id)).toEqual(["new"]);
    expect(merged.episodesUsedInReplies).toBe(true);
    expect(merged.factsUsedInReplies).toBe(true);
  });

  it("is empty when nothing has loaded", () => {
    expect(mergeMemoryItemPages([])).toEqual({
      episodes: [],
      facts: [],
      hasMoreEpisodes: false,
      episodesUsedInReplies: false,
      factsUsedInReplies: false,
    });
  });
});
