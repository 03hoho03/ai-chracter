import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { chatModelKeys, DEFAULT_CHAT_MODEL, type ChatModel } from "@/entities/chat-model";
import { ApiErrorObject } from "@/shared/api/client";

import { previewConfirmTurnCost } from "./previewConfirmTurnCost";

function models(turnCost: number): ChatModel[] {
  // 이 계산이 읽는 칸은 id·turnCost 둘이라 나머지는 비워 둔다.
  return [{ id: DEFAULT_CHAT_MODEL, turnCost } as unknown as ChatModel];
}

const priceChanged = new ApiErrorObject({
  status: 409,
  detail: { code: "CLOVER_PRICE_CHANGED", currentCost: 20 },
  message: "conflict",
});
const confirmRequired = new ApiErrorObject({
  status: 429,
  detail: { code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 10, window: "clover" },
  message: "limit",
});

describe("미리보기 확인 모달의 한 턴 금액", () => {
  it("요청 시점의 모델 목록 캐시에서 읽는다 — 화면을 그린 뒤 바뀐 가격을 놓치지 않는다", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(chatModelKeys.all, models(10));
    queryClient.setQueryData(chatModelKeys.all, models(20));

    expect(await previewConfirmTurnCost(queryClient, confirmRequired, DEFAULT_CHAT_MODEL)).toBe(20);
  });

  it("가격 바뀜 거절이면 모델 목록을 다시 받은 뒤의 값을 돌려준다 — 이어지는 하루 한 번 확인이 새 가격을 말한다", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(chatModelKeys.all, models(10));
    const refetch = vi.spyOn(queryClient, "refetchQueries").mockImplementation(() => {
      queryClient.setQueryData(chatModelKeys.all, models(20));
      return Promise.resolve();
    });

    expect(await previewConfirmTurnCost(queryClient, priceChanged, DEFAULT_CHAT_MODEL)).toBe(20);
    expect(refetch).toHaveBeenCalledWith({ queryKey: chatModelKeys.all });
    // 다음 요청의 하루 한 번 확인도 새 값을 읽는다.
    expect(await previewConfirmTurnCost(queryClient, confirmRequired, DEFAULT_CHAT_MODEL)).toBe(20);
  });

  it("다른 오류에서는 다시 받지 않는다", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(chatModelKeys.all, models(10));
    const refetch = vi.spyOn(queryClient, "refetchQueries");

    await previewConfirmTurnCost(queryClient, confirmRequired, DEFAULT_CHAT_MODEL);
    expect(refetch).not.toHaveBeenCalled();
  });

  it("목록이 없으면 금액을 모른다", async () => {
    expect(await previewConfirmTurnCost(new QueryClient(), confirmRequired, DEFAULT_CHAT_MODEL)).toBeUndefined();
  });
});
