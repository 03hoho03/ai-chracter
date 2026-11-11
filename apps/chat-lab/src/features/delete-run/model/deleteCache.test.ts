import { QueryClient } from "@tanstack/react-query";
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { runKeys } from "@/shared/api/runKeys";
import { hostedRunKeys } from "@/shared/api/service/hostedRuns";

import { clearDeletedRunCache, clearIfAlreadyDeleted } from "./deleteCache";

const RUN_A = "cnVucy9hL2NoYXQuanNvbmw";
const RUN_B = "cnVucy9iL2NoYXQuanNvbmw";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);

/** 서비스 목록 한 줄 — 정리는 런 id 와 최신 판 sha 만 본다. */
function hostedItem(runId: string, sha256: string) {
  return {
    runId,
    versionCount: 2,
    latest: { sha256, versionNumber: 2, raw: false, contractVersion: 1 },
    run: { runId, path: `${runId}/chat.jsonl`, group: null, format: "current", supported: true, roomId: "room" },
  };
}

/** 두 런을 열어 본 뒤의 캐시: 목록, 두 런의 묶음, 두 런의 상세·턴·지표. */
function seededClient(): QueryClient {
  const queryClient = new QueryClient();
  queryClient.setQueryData(hostedRunKeys.list(), { items: [hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)] });
  for (const [runId, sha256] of [
    [RUN_A, SHA_A],
    [RUN_B, SHA_B],
  ] as const) {
    queryClient.setQueryData(hostedRunKeys.bundle(runId, sha256), { contractVersion: 1, runId });
    queryClient.setQueryData(runKeys.detail(runId), { runId });
    queryClient.setQueryData(runKeys.turn(runId, 1), { turn: 1 });
    queryClient.setQueryData(runKeys.metrics(runId), { turns: [] });
  }
  return queryClient;
}

function cachedCount(queryClient: QueryClient, queryKey: ReadonlyArray<unknown>): number {
  return queryClient.getQueryCache().findAll({ queryKey }).length;
}

/** 서비스가 2xx 가 아닌 응답을 줬을 때 axios 가 reject 하는 오류와 같은 꼴. */
function rejectedWith(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_REQUEST, config, {}, {
    data,
    status,
    statusText: "",
    headers: {},
    config,
  });
}

/** 런 A 를 지운 뒤의 캐시인지 — 성공과 이미 지워짐(404)이 같은 정리를 했는지 같은 잣대로 본다. */
function expectRunACleared(queryClient: QueryClient) {
  expect(queryClient.getQueryData(hostedRunKeys.list())).toEqual({ items: [hostedItem(RUN_B, SHA_B)] });
  // 다시 받지 않는다 — 다른 런의 최신 판이 바뀌면 이미 열어 둔 옛 판과 새 판이 한 화면에 섞인다.
  expect(queryClient.getQueryState(hostedRunKeys.list())?.isInvalidated).toBe(false);
  expect(cachedCount(queryClient, hostedRunKeys.bundlesOf(RUN_A))).toBe(0);
  expect(cachedCount(queryClient, runKeys.run(RUN_A))).toBe(0);
  expect(queryClient.getQueryData(hostedRunKeys.bundle(RUN_B, SHA_B))).toBeDefined();
  expect(cachedCount(queryClient, runKeys.run(RUN_B))).toBe(3);
}

describe("clearDeletedRunCache", () => {
  it("지운 런만 목록 캐시에서 빠지고 다른 런의 최신 판은 그대로다 — 목록을 다시 받지 않는다", () => {
    const queryClient = seededClient();

    clearDeletedRunCache(queryClient, RUN_A);

    expect(queryClient.getQueryData(hostedRunKeys.list())).toEqual({ items: [hostedItem(RUN_B, SHA_B)] });
    expect(queryClient.getQueryState(hostedRunKeys.list())?.isInvalidated).toBe(false);
  });

  it("지운 런의 묶음·상세·턴·지표 캐시는 제거된다 — 다른 런의 것은 남는다", () => {
    const queryClient = seededClient();

    clearDeletedRunCache(queryClient, RUN_A);

    expectRunACleared(queryClient);
  });
});

describe("clearIfAlreadyDeleted", () => {
  it("서비스가 404 로 답하면 이미 지워진 것으로 같은 정리를 한다", () => {
    const queryClient = seededClient();

    const isAlreadyDeleted = clearIfAlreadyDeleted(
      queryClient,
      RUN_A,
      rejectedWith(404, { detail: "그런 런이 없다", reason: "notFound" }),
    );

    expect(isAlreadyDeleted).toBe(true);
    expectRunACleared(queryClient);
  });

  it("404 가 아닌 실패는 캐시를 건드리지 않는다 — 대화에 실패를 보이고 다시 누를 수 있다", () => {
    const failures: Array<[string, unknown]> = [
      ["서비스 오류", rejectedWith(503, { detail: "DB 를 쓰지 못했다", reason: "dbUnavailable" })],
      ["세션 끝남", rejectedWith(401, { detail: "로그인이 필요하다", reason: "unauthenticated" })],
      ["응답 없음", new AxiosError("Network Error", AxiosError.ERR_NETWORK)],
    ];

    for (const [label, error] of failures) {
      const queryClient = seededClient();

      expect(clearIfAlreadyDeleted(queryClient, RUN_A, error), label).toBe(false);
      expect(queryClient.getQueryData(hostedRunKeys.list()), label).toEqual({
        items: [hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)],
      });
      expect(cachedCount(queryClient, hostedRunKeys.bundlesOf(RUN_A)), label).toBe(1);
      expect(cachedCount(queryClient, runKeys.run(RUN_A)), label).toBe(3);
    }
  });
});

describe("clearDeletedRunCache 의 받은 때", () => {
  it("지운 뒤에도 목록을 받은 때는 그대로다 — 목록 머리의 받은 때가 지운 시각으로 바뀌지 않는다", () => {
    const queryClient = new QueryClient();
    const receivedAt = 1_700_000_000_000;
    queryClient.setQueryData(
      hostedRunKeys.list(),
      { items: [hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)] },
      { updatedAt: receivedAt },
    );

    clearDeletedRunCache(queryClient, RUN_A);

    expect(queryClient.getQueryData(hostedRunKeys.list())).toEqual({ items: [hostedItem(RUN_B, SHA_B)] });
    expect(queryClient.getQueryState(hostedRunKeys.list())?.dataUpdatedAt).toBe(receivedAt);
  });
});
