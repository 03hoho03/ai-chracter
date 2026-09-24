import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { sessionKeys } from "../api/keys";
import { resetSessionIfLost } from "./resetSessionIfLost";

const ME = { id: "u1" };
const SESSION_LOST = new ApiErrorObject({ status: 401, message: "x", detail: "Not authenticated" });

describe("resetSessionIfLost", () => {
  it("세션 데이터가 있고 세션 소실 401이면 세션을 비운다", () => {
    const qc = new QueryClient();
    qc.setQueryData(sessionKeys.current(), ME);

    resetSessionIfLost(qc, SESSION_LOST);

    expect(qc.getQueryData(sessionKeys.current())).toBeUndefined();
  });

  it("정지 403도 세션을 비운다", () => {
    const qc = new QueryClient();
    qc.setQueryData(sessionKeys.current(), ME);

    resetSessionIfLost(qc, new ApiErrorObject({ status: 403, message: "x", detail: "Account suspended" }));

    expect(qc.getQueryData(sessionKeys.current())).toBeUndefined();
  });

  it("다른 실패는 세션을 건드리지 않는다", () => {
    const qc = new QueryClient();
    qc.setQueryData(sessionKeys.current(), ME);

    resetSessionIfLost(qc, new ApiErrorObject({ status: 401, message: "x", detail: "Invalid email or password" }));
    resetSessionIfLost(qc, new ApiErrorObject({ status: 500, message: "x", detail: undefined }));

    expect(qc.getQueryData(sessionKeys.current())).toEqual(ME);
  });

  it("세션 쿼리가 data 없이 실패한 상태면(로그인 화면·리셋 직후) 리셋하지 않는다", async () => {
    const qc = new QueryClient();
    // 세션 쿼리 자신이 401로 실패한 상태 — 쿼리는 캐시에 있고 data만 없다. 여기서 리셋하면 활성
    // 구독자가 다시 가져와 또 401 → 또 리셋으로 끝없이 돈다(가드가 막아야 하는 바로 그 경우).
    await qc
      .fetchQuery({ queryKey: sessionKeys.current(), queryFn: () => Promise.reject(SESSION_LOST), retry: false })
      .catch(() => {});
    expect(qc.getQueryState(sessionKeys.current())?.status).toBe("error");
    const resetSpy = vi.spyOn(qc, "resetQueries");

    resetSessionIfLost(qc, SESSION_LOST);

    expect(resetSpy).not.toHaveBeenCalled();
  });
});
