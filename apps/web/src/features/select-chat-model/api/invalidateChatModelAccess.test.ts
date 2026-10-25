import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { chatModelKeys } from "@/entities/chat-model";
import { sessionKeys } from "@/entities/session";

import { invalidateChatModelAccess } from "./invalidateChatModelAccess";

describe("invalidateChatModelAccess", () => {
  it("세션과 모델 목록을 낡음으로 표시하고 다른 캐시는 건드리지 않는다", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(sessionKeys.current(), { id: "u1" });
    queryClient.setQueryData(chatModelKeys.all, [{ id: "gemini" }]);
    queryClient.setQueryData(["unrelated"], 1);

    invalidateChatModelAccess(queryClient);

    expect(queryClient.getQueryState(sessionKeys.current())?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(chatModelKeys.all)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(["unrelated"])?.isInvalidated).toBe(false);
  });
});
