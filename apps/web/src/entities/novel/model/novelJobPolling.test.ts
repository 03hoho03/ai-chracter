import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  getNovelJobRefetchInterval,
  getNovelJobStaleTime,
  hasNovelJobPollError,
  isTerminalNovelJobStatus,
  NOVEL_JOB_ERROR_POLL_INTERVAL_MS,
  NOVEL_JOB_POLL_INTERVAL_MS,
} from "./novelJobPolling";

const serverDown = new ApiErrorObject({ status: 503, message: "x", detail: undefined });
const networkDown = new ApiErrorObject({ status: 0, message: "x", detail: undefined });
const jobGone = new ApiErrorObject({ status: 404, message: "x", detail: { code: "NOVEL_JOB_NOT_FOUND" } });

describe("isTerminalNovelJobStatus", () => {
  it.each([
    ["succeeded", true],
    ["failed", true],
    ["queued", false],
    ["running", false],
    [undefined, false],
  ] as const)("%s → %s", (status, expected) => {
    expect(isTerminalNovelJobStatus(status)).toBe(expected);
  });
});

describe("hasNovelJobPollError", () => {
  it("오류가 마지막 성공보다 최근이면 참", () => {
    expect(hasNovelJobPollError({ errorUpdatedAt: 20, dataUpdatedAt: 10 })).toBe(true);
  });

  it("오류 뒤에 성공했으면 회복한 것이다", () => {
    expect(hasNovelJobPollError({ errorUpdatedAt: 10, dataUpdatedAt: 20 })).toBe(false);
  });

  it("아직 아무 응답도 없는 새 작업은 오류가 아니다", () => {
    expect(hasNovelJobPollError({ errorUpdatedAt: 0, dataUpdatedAt: 0 })).toBe(false);
  });
});

describe("getNovelJobRefetchInterval", () => {
  const fresh = { error: null, errorUpdatedAt: 0, dataUpdatedAt: 0 };

  it("첫 응답 전에는 보통 간격으로 묻는다", () => {
    expect(getNovelJobRefetchInterval({ ...fresh, data: undefined })).toBe(NOVEL_JOB_POLL_INTERVAL_MS);
  });

  it.each(["queued", "running"] as const)("%s 이면 보통 간격으로 묻는다", (status) => {
    expect(getNovelJobRefetchInterval({ ...fresh, data: { status }, dataUpdatedAt: 5 })).toBe(NOVEL_JOB_POLL_INTERVAL_MS);
  });

  it.each(["succeeded", "failed"] as const)("%s 이면 멈춘다", (status) => {
    expect(getNovelJobRefetchInterval({ ...fresh, data: { status }, dataUpdatedAt: 5 })).toBe(false);
  });

  // 이미지 작업은 여기서 멈춘다. 장 작업이 멈추면 서버가 다시 뜬 뒤에도 회복하지 못한다.
  it.each([
    ["서버 오류", serverDown],
    ["네트워크 끊김", networkDown],
  ])("%s 로 조회가 실패하고 있어도 멈추지 않고 느린 간격으로 계속 묻는다", (_label, error) => {
    expect(
      getNovelJobRefetchInterval({ data: { status: "running" }, error, errorUpdatedAt: 20, dataUpdatedAt: 10 }),
    ).toBe(NOVEL_JOB_ERROR_POLL_INTERVAL_MS);
  });

  it("응답을 한 번도 못 받은 채 실패해도 느린 간격으로 계속 묻는다", () => {
    expect(getNovelJobRefetchInterval({ data: undefined, error: serverDown, errorUpdatedAt: 20, dataUpdatedAt: 0 })).toBe(
      NOVEL_JOB_ERROR_POLL_INTERVAL_MS,
    );
  });

  it("오류 뒤 다시 성공하면 보통 간격으로 돌아온다", () => {
    expect(
      getNovelJobRefetchInterval({ data: { status: "running" }, error: serverDown, errorUpdatedAt: 10, dataUpdatedAt: 20 }),
    ).toBe(NOVEL_JOB_POLL_INTERVAL_MS);
  });

  it("작업이 없어졌다는 404 면 멈춘다 — 다시 물어도 같은 답이다", () => {
    expect(
      getNovelJobRefetchInterval({ data: { status: "running" }, error: jobGone, errorUpdatedAt: 20, dataUpdatedAt: 10 }),
    ).toBe(false);
  });

  it("끝난 결과를 받은 뒤의 오류는 다시 묻지 않는다", () => {
    expect(
      getNovelJobRefetchInterval({ data: { status: "succeeded" }, error: serverDown, errorUpdatedAt: 20, dataUpdatedAt: 10 }),
    ).toBe(false);
  });
});

describe("getNovelJobStaleTime", () => {
  it("끝난 작업은 다시 묻지 않는다", () => {
    expect(getNovelJobStaleTime({ status: "succeeded" })).toBe(Infinity);
    expect(getNovelJobStaleTime({ status: "failed" })).toBe(Infinity);
  });

  it("진행 중이거나 아직 모르면 포커스 복귀 때 바로 묻는다", () => {
    expect(getNovelJobStaleTime({ status: "running" })).toBe(0);
    expect(getNovelJobStaleTime(undefined)).toBe(0);
  });
});
