import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageJobStatus } from "./imageJobStatus";
import {
  getImageJobRefetchInterval,
  getImageJobStaleTime,
  hasImageJobPollError,
  isTerminalImageJobStatus,
} from "./imageJobStatus";

describe("isTerminalImageJobStatus", () => {
  it("succeeded·failed 만 터미널이다", () => {
    expect(isTerminalImageJobStatus("succeeded")).toBe(true);
    expect(isTerminalImageJobStatus("failed")).toBe(true);
  });

  it("queued·running 과 첫 응답 전(undefined)은 터미널이 아니다", () => {
    expect(isTerminalImageJobStatus("queued")).toBe(false);
    expect(isTerminalImageJobStatus("running")).toBe(false);
    expect(isTerminalImageJobStatus(undefined)).toBe(false);
  });
});

describe("getImageJobRefetchInterval", () => {
  it("조회가 오류 상태면 폴링을 멈춘다(data 가 남아 있어도)", () => {
    expect(getImageJobRefetchInterval({ status: "error", data: undefined })).toBe(false);
    expect(getImageJobRefetchInterval({ status: "error", data: { status: "running" } })).toBe(false);
  });

  it("터미널 잡이면 폴링을 멈춘다", () => {
    expect(getImageJobRefetchInterval({ status: "success", data: { status: "succeeded" } })).toBe(false);
    expect(getImageJobRefetchInterval({ status: "success", data: { status: "failed" } })).toBe(false);
  });

  it("첫 응답 전이거나 진행 중이면 1.5초마다 묻는다", () => {
    expect(getImageJobRefetchInterval({ status: "pending", data: undefined })).toBe(1500);
    expect(getImageJobRefetchInterval({ status: "success", data: { status: "running" } })).toBe(1500);
    expect(getImageJobRefetchInterval({ status: "success", data: { status: "queued" } })).toBe(1500);
  });
});

describe("getImageJobStaleTime", () => {
  it("터미널 data 는 다시 묻지 않고, 그 외에는 바로 낡은 것으로 본다", () => {
    expect(getImageJobStaleTime({ status: "succeeded" })).toBe(Infinity);
    expect(getImageJobStaleTime({ status: "failed" })).toBe(Infinity);
    expect(getImageJobStaleTime({ status: "running" })).toBe(0);
    expect(getImageJobStaleTime(undefined)).toBe(0);
  });
});

describe("hasImageJobPollError", () => {
  it("성공도 오류도 없는 새 잡은 오류가 아니다", () => {
    expect(hasImageJobPollError({ errorUpdatedAt: 0, dataUpdatedAt: 0 })).toBe(false);
  });

  it("한 번도 성공하지 못하고 실패했으면 오류다", () => {
    expect(hasImageJobPollError({ errorUpdatedAt: 1000, dataUpdatedAt: 0 })).toBe(true);
  });

  it("오류 뒤에 성공이 오면 회복한 것이다", () => {
    expect(hasImageJobPollError({ errorUpdatedAt: 1000, dataUpdatedAt: 2000 })).toBe(false);
  });

  it("성공 뒤에 오류가 오면 오류다", () => {
    expect(hasImageJobPollError({ errorUpdatedAt: 2000, dataUpdatedAt: 1000 })).toBe(true);
  });
});

// 실제 query-core 로 상태 전이를 만든다 — 판정이 기대는 성질(재조회·재시도 동안 status 가 pending 으로
// 돌아가도 두 시각은 성공·최종 오류에서만 바뀐다)이 라이브러리 판올림에서 바뀌면 여기서 드러난다.
describe("실제 QueryClient 상태 전이", () => {
  type Job = { status: ImageJobStatus };
  const queryKey = ["image-job", "status", "job-1"];
  let now = 1_000;

  // 성공과 오류가 같은 밀리초에 찍히면 비교가 갈리지 않으므로 단계마다 시계를 민다.
  const tick = () => {
    now += 1_000;
    vi.setSystemTime(now);
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(now);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function judge(queryClient: QueryClient) {
    const state = queryClient.getQueryCache().find<Job>({ queryKey })?.state;
    if (state === undefined) throw new Error("쿼리가 캐시에 없다");
    return {
      status: state.status,
      hasPollError: hasImageJobPollError(state),
      refetchInterval: getImageJobRefetchInterval(state),
    };
  }

  // 훅이 쓰는 staleTime 으로 본 낡음 — 창 포커스·재연결 재조회는 이 값이 참일 때만 나간다.
  function isStaleForHook(queryClient: QueryClient) {
    const query = queryClient.getQueryCache().find<Job>({ queryKey });
    if (query === undefined) throw new Error("쿼리가 캐시에 없다");
    return query.isStaleByTime(getImageJobStaleTime(query.state.data));
  }

  function deferred() {
    let resolve: (job: Job) => void = () => undefined;
    let reject: (error: Error) => void = () => undefined;
    const promise = new Promise<Job>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  }

  it("실패 → 재시도 중 → 성공: 재시도 동안 오류가 유지되고 성공하면 폴링을 재개한다", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, retryDelay: 0 } } });

    await queryClient
      .fetchQuery<Job>({ queryKey, queryFn: () => Promise.reject(new Error("500")) })
      .catch(() => undefined);
    expect(judge(queryClient)).toEqual({ status: "error", hasPollError: true, refetchInterval: false });

    // 창 포커스 재조회: 첫 시도는 실패하고 재시도가 응답을 기다리는 중이다.
    tick();
    const retry = deferred();
    const queryFn = vi
      .fn<() => Promise<Job>>()
      .mockRejectedValueOnce(new Error("500"))
      .mockReturnValueOnce(retry.promise);
    const refetch = queryClient.fetchQuery<Job>({ queryKey, queryFn });
    await vi.waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
    expect(judge(queryClient)).toEqual({ status: "pending", hasPollError: true, refetchInterval: 1500 });

    tick();
    retry.resolve({ status: "running" });
    await refetch;
    expect(judge(queryClient)).toEqual({ status: "success", hasPollError: false, refetchInterval: 1500 });
  });

  it("성공(running) → 실패: data 가 남아도 오류로 보고 폴링을 멈춘다, 포커스 재조회가 완료를 받으면 회복한다", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    await queryClient.fetchQuery<Job>({ queryKey, queryFn: () => Promise.resolve({ status: "running" }) });
    expect(judge(queryClient)).toEqual({ status: "success", hasPollError: false, refetchInterval: 1500 });

    tick();
    await queryClient
      .fetchQuery<Job>({ queryKey, queryFn: () => Promise.reject(new Error("500")) })
      .catch(() => undefined);
    expect(judge(queryClient)).toEqual({ status: "error", hasPollError: true, refetchInterval: false });
    expect(queryClient.getQueryData<Job>(queryKey)).toEqual({ status: "running" });

    // 오류가 쿼리를 무효로 표시하므로 진행 중 data 라도 창 포커스 재조회 대상이다.
    expect(isStaleForHook(queryClient)).toBe(true);

    tick();
    await queryClient.fetchQuery<Job>({ queryKey, queryFn: () => Promise.resolve({ status: "succeeded" }) });
    expect(judge(queryClient)).toEqual({ status: "success", hasPollError: false, refetchInterval: false });
    // 완료된 잡은 창 포커스로 다시 묻지 않는다 — TTL 뒤 404 가 완료 결과를 덮지 않게.
    expect(isStaleForHook(queryClient)).toBe(false);
  });
});
