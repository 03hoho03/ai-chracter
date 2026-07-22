import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { previewSessionKeys } from "../api/keys";
import type { PreviewSessionState } from "../api/preview-session";
import { applyPreviewStreamEvent } from "./applyPreviewStreamEvent";

const SESSION_ID = "preview-1";

function buildState(overrides: Partial<PreviewSessionState> = {}): PreviewSessionState {
  return {
    previewSessionId: SESSION_ID,
    contentType: "story",
    messages: [{ id: "m1", role: "assistant", content: "안녕", createdAt: "2026-07-08T00:00:00Z" }],
    stats: { hp: 50 },
    statDefs: [],
    shortcuts: [],
    suggestedReplies: [],
    endingStatus: { reached: false, epilogue: null },
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
