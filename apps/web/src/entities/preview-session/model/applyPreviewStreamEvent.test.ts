import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { previewSessionKeys } from "../api/keys";
import { previewStreamEventSchema } from "../api/previewStream";
import { applyPreviewStreamEvent } from "./applyPreviewStreamEvent";
import type { PreviewSessionState } from "./previewSessionState";

const SESSION_ID = "preview-1";

function buildState(overrides: Partial<PreviewSessionState> = {}): PreviewSessionState {
  return {
    previewSessionId: SESSION_ID,
    contentType: "story",
    authorNameSource: { contentName: "여름밤의 항해" },
    messages: [{ id: "m1", role: "assistant", content: "안녕", createdAt: "2026-07-08T00:00:00Z" }],
    openingMediaTagImages: {},
    stats: { hp: 50 },
    statDefs: [],
    shortcuts: [],
    suggestedReplies: [],
    endingStatus: { reached: false, epilogue: undefined },
    turnCount: 3,
    ...overrides,
  };
}

describe("applyPreviewStreamEvent", () => {
  let queryClient: QueryClient;
  let initialState: PreviewSessionState;

  beforeEach(() => {
    queryClient = new QueryClient();
    initialState = buildState();
    queryClient.setQueryData(previewSessionKeys.detail(SESSION_ID), initialState);
  });

  it("does not touch the cache for token/policyWarning/error", () => {
    applyPreviewStreamEvent(queryClient, SESSION_ID, { type: "token", delta: "hi" });
    applyPreviewStreamEvent(queryClient, SESSION_ID, { type: "policyWarning", message: "주의" });
    applyPreviewStreamEvent(queryClient, SESSION_ID, { type: "error", message: "네트워크 오류" });

    expect(queryClient.getQueryData(previewSessionKeys.detail(SESSION_ID))).toBe(initialState);
  });

  it("statChange overwrites with the event's absolute newValue", () => {
    applyPreviewStreamEvent(queryClient, SESSION_ID, { type: "statChange", statId: "hp", newValue: 12 });

    expect(
      queryClient.getQueryData<PreviewSessionState>(previewSessionKeys.detail(SESSION_ID))?.stats,
    ).toEqual({ hp: 12 });
  });

  it("endingReached sets endingStatus with the event's epilogue", () => {
    applyPreviewStreamEvent(queryClient, SESSION_ID, { type: "endingReached", endingId: "ending-1", epilogue: "끝" });

    expect(
      queryClient.getQueryData<PreviewSessionState>(previewSessionKeys.detail(SESSION_ID))?.endingStatus,
    ).toEqual({ reached: true, epilogue: "끝" });
  });

  it("done appends the final message and increments turnCount", () => {
    const finalMessage = { id: "m2", role: "assistant" as const, content: "다음 대사", createdAt: "2026-07-08T00:01:00Z" };

    applyPreviewStreamEvent(queryClient, SESSION_ID, { type: "done", finalMessage });

    const next = queryClient.getQueryData<PreviewSessionState>(previewSessionKeys.detail(SESSION_ID));
    expect(next?.messages).toEqual([...initialState.messages, finalMessage]);
    expect(next?.turnCount).toBe(4);
  });

  // 와이어 모양 그대로 스키마를 지나게 한다 — 스키마가 그림 필드를 모르면 zod 가 조용히 버려서,
  // 이벤트 객체를 직접 만들어 넣는 테스트로는 미리보기 판정 이미지가 0장인 것을 못 잡는다.
  it("done keeps the judged image fields from the wire through to the cached message", () => {
    const wire = {
      type: "done",
      finalMessage: {
        id: "m2",
        role: "assistant",
        content: "다음 대사",
        createdAt: "2026-07-08T00:01:00Z",
        imageId: "cell-1",
        imageUrl: "https://r2.example/cell-1.webp",
        imageWidth: 768,
        imageHeight: 1024,
      },
    };

    applyPreviewStreamEvent(queryClient, SESSION_ID, previewStreamEventSchema.parse(wire));

    const next = queryClient.getQueryData<PreviewSessionState>(previewSessionKeys.detail(SESSION_ID));
    expect(next?.messages.at(-1)).toEqual(wire.finalMessage);
  });

  // 캐릭터 미리보기는 서버가 판정하지 않아 그림 필드를 null 로 싣는다 — 메시지는 이전처럼 글만 남는다.
  it("done from a character preview (null image fields) leaves the message text-only", () => {
    const wire = {
      type: "done",
      finalMessage: {
        id: "m2",
        role: "assistant",
        content: "다음 대사",
        createdAt: "2026-07-08T00:01:00Z",
        imageId: null,
        imageUrl: null,
        imageWidth: null,
        imageHeight: null,
      },
    };

    applyPreviewStreamEvent(queryClient, SESSION_ID, previewStreamEventSchema.parse(wire));

    const last = queryClient.getQueryData<PreviewSessionState>(previewSessionKeys.detail(SESSION_ID))?.messages.at(-1);
    expect(last).toEqual({ id: "m2", role: "assistant", content: "다음 대사", createdAt: "2026-07-08T00:01:00Z" });
    expect(last?.imageUrl).toBeUndefined();
  });

  it("is a no-op when there is no cached state yet for the session", () => {
    const emptyClient = new QueryClient();

    applyPreviewStreamEvent(emptyClient, SESSION_ID, { type: "statChange", statId: "hp", newValue: 1 });
    applyPreviewStreamEvent(emptyClient, SESSION_ID, { type: "endingReached", endingId: "e1", epilogue: null });
    applyPreviewStreamEvent(emptyClient, SESSION_ID, {
      type: "done",
      finalMessage: { id: "m1", role: "assistant", content: "x", createdAt: "2026-07-08T00:00:00Z" },
    });

    expect(emptyClient.getQueryData(previewSessionKeys.detail(SESSION_ID))).toBeUndefined();
  });
});
