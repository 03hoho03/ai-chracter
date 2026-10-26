import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { cloverKeys, readCloverPricing, type CloverPricingResponse } from "@/entities/clover";
import { apiClient, ApiErrorObject } from "@/shared/api/client";

import { confirmCloverPriceChange } from "./confirmCloverPriceChange";

function pricing(priceVersion: number): CloverPricingResponse {
  // 이 확인이 읽는 칸은 가격 버전 하나라 나머지는 비워 둔다.
  return { priceVersion } as unknown as CloverPricingResponse;
}

const priceChanged = new ApiErrorObject({
  status: 409,
  detail: { code: "CLOVER_PRICE_CHANGED", currentCost: 60 },
  message: "conflict",
});

function seededClient(): QueryClient {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(cloverKeys.pricing(), pricing(1));
  return queryClient;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("가격 바뀜 확인", () => {
  it("가격표를 다시 받은 뒤 지금 금액으로 한 번 묻고, 확인하면 다시 보내라고 돌려준다", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: pricing(2) });
    const queryClient = seededClient();
    const ask = vi.fn().mockResolvedValue(true);

    const outcome = await confirmCloverPriceChange(queryClient, priceChanged, ask);

    expect(outcome).toBe("retry");
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask).toHaveBeenCalledWith(60);
    // 다시 보내는 요청은 이 값을 싣는다 — 새 가격표의 버전이다.
    expect(readCloverPricing(queryClient)?.priceVersion).toBe(2);
  });

  it("사용자가 답하기 전에는 끝나지 않는다 — 저절로 다시 보내지 않는다", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: pricing(2) });
    const ask = vi.fn(() => new Promise<boolean>(() => {}));
    let settled = false;

    void confirmCloverPriceChange(seededClient(), priceChanged, ask).then(() => {
      settled = true;
    });
    await vi.waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(settled).toBe(false);
  });

  it("그만두면 다시 보내지 않는다", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: pricing(2) });
    const outcome = await confirmCloverPriceChange(seededClient(), priceChanged, vi.fn().mockResolvedValue(false));
    expect(outcome).toBe("declined");
  });

  it("가격표를 다시 받지 못하면 묻지 않는다 — 옛 버전으로 다시 보내면 같은 거절이다", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue(new Error("network"));
    const ask = vi.fn().mockResolvedValue(true);

    const outcome = await confirmCloverPriceChange(seededClient(), priceChanged, ask);

    expect(outcome).toBe("unhandled");
    expect(ask).not.toHaveBeenCalled();
  });

  it("가격 바뀜이 아닌 오류는 다루지 않는다", async () => {
    const get = vi.spyOn(apiClient, "get");
    const ask = vi.fn();
    const other = new ApiErrorObject({ status: 500, detail: undefined, message: "boom" });

    expect(await confirmCloverPriceChange(seededClient(), other, ask)).toBe("unhandled");
    expect(get).not.toHaveBeenCalled();
    expect(ask).not.toHaveBeenCalled();
  });
});
