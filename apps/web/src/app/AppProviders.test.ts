import { QueryObserver, type QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sessionKeys, sessionQueryOptions, type MeResponse } from "@/entities/session";
import { ApiErrorObject } from "@/shared/api/client";

import { createQueryClient } from "./AppProviders";

const ME: MeResponse = {
  id: "u1",
  email: "u1@example.com",
  nickname: "u1",
  bio: null,
  profileImageAssetId: null,
  termsReconsentRequired: false,
  privacyReconsentRequired: false,
};
const SESSION_LOST = new ApiErrorObject({ status: 401, message: "x", detail: "Not authenticated" });

let client: QueryClient | undefined;

function makeClient(): QueryClient {
  client = createQueryClient();
  return client;
}

afterEach(() => {
  client?.clear();
  client = undefined;
});

function runMutation(qc: QueryClient, error: Error) {
  return qc.getMutationCache().build(qc, { mutationFn: () => Promise.reject(error) }).execute(undefined);
}

function failQuery(qc: QueryClient, error: Error) {
  return qc.fetchQuery({ queryKey: ["other"], queryFn: () => Promise.reject(error) });
}

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

describe("createQueryClient — 세션 소실 전역 처리 (backlog-l-goal-prompt.md BL-6)", () => {
  it("(a) 세션 데이터가 있는데 다른 쿼리가 401 Not authenticated로 실패하면 세션을 리셋한다", async () => {
    const qc = makeClient();
    qc.setQueryData(sessionKeys.current(), ME);

    await expect(failQuery(qc, SESSION_LOST)).rejects.toBe(SESSION_LOST);
    await flush();

    expect(qc.getQueryData(sessionKeys.current())).toBeUndefined();
  });

  it("정지 403도 세션을 리셋한다", async () => {
    const qc = makeClient();
    qc.setQueryData(sessionKeys.current(), ME);
    const suspended = new ApiErrorObject({ status: 403, message: "x", detail: "Account suspended" });

    await expect(failQuery(qc, suspended)).rejects.toBe(suspended);
    await flush();

    expect(qc.getQueryData(sessionKeys.current())).toBeUndefined();
  });

  it("(b) 세션 데이터가 없으면(로그인 화면) 세션 쿼리를 건드리지 않는다", async () => {
    const qc = makeClient();
    const resetSpy = vi.spyOn(qc, "resetQueries");

    await expect(failQuery(qc, SESSION_LOST)).rejects.toBe(SESSION_LOST);
    await expect(runMutation(qc, SESSION_LOST)).rejects.toBe(SESSION_LOST);
    await flush();

    expect(resetSpy).not.toHaveBeenCalled();
  });

  it("(c) 로그인 실패 401('Invalid email or password')은 무시한다", async () => {
    const qc = makeClient();
    qc.setQueryData(sessionKeys.current(), ME);
    const loginFailed = new ApiErrorObject({ status: 401, message: "x", detail: "Invalid email or password" });

    await expect(runMutation(qc, loginFailed)).rejects.toBe(loginFailed);
    await expect(failQuery(qc, loginFailed)).rejects.toBe(loginFailed);
    await flush();

    expect(qc.getQueryData(sessionKeys.current())).toEqual(ME);
  });

  it("(d) 세션 쿼리 자신이 401이어도 리셋→리페치가 무한 반복되지 않는다", async () => {
    const qc = makeClient();
    let calls = 0;
    const queryFn = () => {
      calls += 1;
      // 가드가 없으면 끝없이 돈다 — 상한에서 영원히 대기하는 promise로 루프를 끊어 테스트가 끝나게 한다
      // (그래도 calls가 3을 넘으므로 아래 단언이 빨개진다).
      if (calls > 10) return new Promise<MeResponse>(() => {});
      return calls === 1 ? Promise.resolve(ME) : Promise.reject(SESSION_LOST);
    };
    // 헤더처럼 세션 쿼리를 구독한다 — resetQueries는 활성 쿼리만 다시 가져온다.
    const unsubscribe = new QueryObserver(qc, { ...sessionQueryOptions, queryFn }).subscribe(() => {});
    await flush();
    expect(qc.getQueryData(sessionKeys.current())).toEqual(ME);

    // 포커스 복귀 리페치에 해당한다 — 실패해도 이전 data가 남아 있어 가드를 한 번 통과한다.
    await qc.refetchQueries({ queryKey: sessionKeys.current() }).catch(() => {});
    await flush();
    await flush();

    // 1(로그인) + 1(리페치 401, 옛 data 남음 → 리셋) + 1(리셋 뒤 리페치 401, data 없음 → 가드에서 멈춤)
    expect(calls).toBe(3);
    expect(qc.getQueryData(sessionKeys.current())).toBeUndefined();
    unsubscribe();
  });

  it("(e) 뮤테이션 401 Not authenticated도 세션을 리셋한다", async () => {
    const qc = makeClient();
    qc.setQueryData(sessionKeys.current(), ME);

    await expect(runMutation(qc, SESSION_LOST)).rejects.toBe(SESSION_LOST);
    await flush();

    expect(qc.getQueryData(sessionKeys.current())).toBeUndefined();
  });

  it("재동의 403 뮤테이션은 기존처럼 세션을 invalidate만 한다", async () => {
    const qc = makeClient();
    qc.setQueryData(sessionKeys.current(), ME);
    const reconsent = new ApiErrorObject({
      status: 403,
      message: "x",
      detail: { code: "LEGAL_RECONSENT_REQUIRED" },
    });

    await expect(runMutation(qc, reconsent)).rejects.toBe(reconsent);

    expect(qc.getQueryState(sessionKeys.current())?.isInvalidated).toBe(true);
    expect(qc.getQueryData(sessionKeys.current())).toEqual(ME);
  });
});

describe("createQueryClient — 기본 retry", () => {
  function defaultRetry() {
    const retry = createQueryClient().getDefaultOptions().queries?.retry;
    if (typeof retry !== "function") throw new Error("retry must be a function");
    return retry;
  }

  it.each([
    [0, true],
    [500, true],
    [503, true],
    [401, false],
    [404, false],
    [429, false],
  ])("status %d 재시도 여부는 %s다", (status, expected) => {
    expect(defaultRetry()(0, new ApiErrorObject({ status, message: "x", detail: undefined }))).toBe(expected);
  });

  it("최대 3회다", () => {
    expect(defaultRetry()(3, new ApiErrorObject({ status: 500, message: "x", detail: undefined }))).toBe(false);
  });
});

describe("sessionQueryOptions", () => {
  it("포커스 복귀 때마다 다시 조회한다(staleTime: Infinity여도)", () => {
    expect(sessionQueryOptions.refetchOnWindowFocus).toBe("always");
  });
});
