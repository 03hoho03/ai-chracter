// 담을 대화 단계의 원문 바뀜 안내. 서버는 원문이 바뀐 것을 턴이 아니라 저장한 구간마다 알려(구간 하나가 수십 턴일 수 있다) 표시도
// 그 구간의 턴 전부에 붙는다 — 안내가 "바뀐 턴"이라고 하면 표시가 붙은 턴이 모두 바뀐 것으로 읽힌다.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { chatRoomKeys } from "@/entities/chat-room";
import { novelKeys, type NovelDetailResponse } from "@/entities/novel";

import { NovelSourceSelectionStep } from "./NovelSourceSelectionStep";

const novel = { id: "novel-1", chatRoomId: "room-1" } as unknown as NovelDetailResponse;

const MESSAGES = [
  { id: "u1", role: "user", content: "말 1", createdAt: "2026-10-24T00:00:01Z" },
  { id: "a1", role: "assistant", content: "답 1", createdAt: "2026-10-24T00:00:02Z" },
  { id: "u2", role: "user", content: "말 2", createdAt: "2026-10-24T00:00:03Z" },
  { id: "a2", role: "assistant", content: "답 2", createdAt: "2026-10-24T00:00:04Z" },
];

function render(sourceChanged: boolean): string {
  const client = new QueryClient();
  client.setQueryData(chatRoomKeys.sourceMessages("room-1"), MESSAGES);
  client.setQueryData(novelKeys.sourceSelection(novel.id), {
    approved: {
      revision: 1,
      approvedAt: "2026-10-24T00:00:00Z",
      roomEndMessageId: "a2",
      roomEndMessageCreatedAt: "2026-10-24T00:00:04Z",
      sections: [
        {
          startMessageId: "u1",
          endMessageId: "a2",
          startMessageCreatedAt: "2026-10-24T00:00:01Z",
          endMessageCreatedAt: "2026-10-24T00:00:04Z",
          mode: "include",
          assistantMessageCount: 2,
          sourceChanged,
        },
      ],
    },
    draft: null,
    proposal: null,
    lockedRanges: [],
    roomEndMessageId: "a2",
    hasNewMessages: false,
  });
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client },
      createElement(NovelSourceSelectionStep, { novel, onDraftDirtyChange: () => {} }),
    ),
  );
}

describe("담을 대화 — 원문 바뀜 안내", () => {
  it("바뀐 것이 턴이 아니라 표시한 구간 어딘가라고 말한다", () => {
    const html = render(true);
    expect(html).toContain("고른 뒤 바뀐 구간");
    expect(html).toContain("이 구간 어딘가가 고른 뒤 바뀌었어요");
    expect(html).not.toContain("바뀐 턴");
    expect(html).not.toContain("고른 뒤 바뀜");
  });

  it("원문이 그대로면 안내도 표시도 없다", () => {
    expect(render(false)).not.toContain("고른 뒤 바뀐 구간");
  });
});
