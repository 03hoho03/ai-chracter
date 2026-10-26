import { QueryClient } from "@tanstack/react-query";
import type * as ReactQuery from "@tanstack/react-query";
import type * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { cloverKeys, type CloverPricingResponse, type CloverSpendConfirmOutcome } from "@/entities/clover";

import { useSendMessage } from "./useSendMessage";

// 이 앱에는 훅을 그리는 도구가 없다. 훅이 쓰는 React 상태 훅과 QueryClient 주입만 바꿔 끼워 함수로 부른다 — 상태 갱신은
// 버리지만, 여기서 보는 것은 요청이 몇 번·어떤 본문으로 나가는가라 상태를 그릴 필요가 없다.
const holder = vi.hoisted((): { queryClient: unknown } => ({ queryClient: undefined }));

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof React>();
  return {
    ...actual,
    useState: (initial: unknown) => [typeof initial === "function" ? (initial as () => unknown)() : initial, () => {}],
    useRef: (initial: unknown) => ({ current: initial }),
  };
});

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof ReactQuery>();
  return { ...actual, useQueryClient: () => holder.queryClient };
});

function pricing(priceVersion: number): CloverPricingResponse {
  return { priceVersion } as unknown as CloverPricingResponse;
}

const priceChangedResponse = () =>
  new Response(JSON.stringify({ detail: { code: "CLOVER_PRICE_CHANGED", currentCost: 20 } }), { status: 409 });

let queryClient: QueryClient;
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;

function sentPriceVersions(): unknown[] {
  return fetchMock.mock.calls.map(([, init]) =>
    typeof init?.body === "string" ? (JSON.parse(init.body) as { priceVersion?: number }).priceVersion : undefined,
  );
}

/** 이어지는 요청이 더 없는지 보려고 잠깐 기다린다. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

beforeEach(() => {
  queryClient = new QueryClient();
  queryClient.setQueryData(cloverKeys.pricing(), pricing(1));
  holder.queryClient = queryClient;
  fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("채팅 전송의 가격 바뀜 409", () => {
  it("확인하면 다시 받은 가격표의 버전으로 정확히 한 번 다시 보낸다", async () => {
    fetchMock.mockResolvedValueOnce(priceChangedResponse()).mockResolvedValueOnce(new Response(""));
    // 확인 모달을 대신한다 — 실제 확인처럼 가격표를 다시 받아 캐시에 새 버전을 넣고 다시 보내라고 답한다.
    const confirm = vi.fn((): Promise<CloverSpendConfirmOutcome> => {
      queryClient.setQueryData(cloverKeys.pricing(), pricing(2));
      return Promise.resolve("retry");
    });

    useSendMessage("room-1", undefined, confirm).send("안녕");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await settle();

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sentPriceVersions()).toEqual([1, 2]);
    // 다시 보낸 것은 같은 글이다.
    const secondBody = fetchMock.mock.calls[1]?.[1]?.body;
    expect(typeof secondBody === "string" && (JSON.parse(secondBody) as { content: string }).content).toBe("안녕");
  });

  it("사용자가 답하기 전에는 다시 보내지 않는다", async () => {
    fetchMock.mockResolvedValueOnce(priceChangedResponse());
    const confirm = vi.fn(() => new Promise<CloverSpendConfirmOutcome>(() => {}));

    useSendMessage("room-1", undefined, confirm).send("안녕");
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("그만두면 다시 보내지 않는다", async () => {
    fetchMock.mockResolvedValueOnce(priceChangedResponse());
    const confirm = vi.fn((): Promise<CloverSpendConfirmOutcome> => Promise.resolve("declined"));

    useSendMessage("room-1", undefined, confirm).send("안녕");
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("다시 보낸 요청이 또 가격 바뀜을 받으면 묻지 않고 멈춘다", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(priceChangedResponse()));
    // 차단기가 깨지면 끝없이 묻게 되므로, 세 번째부터는 그만둬 시험이 멈추지 않게 한다.
    const confirm = vi.fn(
      (): Promise<CloverSpendConfirmOutcome> => Promise.resolve(confirm.mock.calls.length < 3 ? "retry" : "declined"),
    );

    useSendMessage("room-1", undefined, confirm).send("안녕");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await settle();

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
