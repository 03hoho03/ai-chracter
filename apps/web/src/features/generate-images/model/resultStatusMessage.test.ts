import { describe, expect, it } from "vitest";

import { getResultStatusMessage, type ResultStatusJob } from "./resultStatusMessage";

function job(overrides: Partial<ResultStatusJob> = {}): ResultStatusJob {
  return {
    status: "running",
    completedCount: 0,
    images: [],
    blockedCount: 0,
    blockedReason: null,
    ...overrides,
  };
}

const IDLE = { isSubmitting: false, hasSubmission: true, requestedCount: 2, hasPollError: false };

describe("getResultStatusMessage", () => {
  it("첫 생성 전(첫 제출이 실패해 스냅샷이 없을 때 포함)에는 아무 문구도 없다", () => {
    expect(
      getResultStatusMessage({ ...IDLE, hasSubmission: false, job: undefined }),
    ).toEqual({ status: "", srSuffix: "", isInProgress: false });
  });

  it("제출 중이면 직전 결과가 완료여도 '요청 보내는 중…'이 이긴다", () => {
    expect(
      getResultStatusMessage({
        ...IDLE,
        isSubmitting: true,
        job: job({ status: "succeeded", completedCount: 2, images: [{ assetId: "a" }, { assetId: "b" }] }),
      }),
    ).toEqual({ status: "요청 보내는 중…", srSuffix: "", isInProgress: true });
  });

  it("202 직후 첫 응답 전에는 0장 진행 문구다", () => {
    expect(getResultStatusMessage({ ...IDLE, job: undefined })).toEqual({
      status: "생성 중… (0/2장)",
      srSuffix: "",
      isInProgress: true,
    });
  });

  it("queued 는 running 0장과 같은 문구다", () => {
    expect(getResultStatusMessage({ ...IDLE, job: job({ status: "queued" }) }).status).toBe("생성 중… (0/2장)");
    expect(getResultStatusMessage({ ...IDLE, job: job({ status: "running" }) }).status).toBe("생성 중… (0/2장)");
  });

  it("한 장이라도 나오면 'c/m장 생성 중…'으로 바뀐다", () => {
    expect(
      getResultStatusMessage({ ...IDLE, job: job({ completedCount: 1, images: [{ assetId: "a" }] }) }),
    ).toEqual({ status: "1/2장 생성 중…", srSuffix: "", isInProgress: true });
  });

  it("완료면 받은 장수로 'n장 생성 완료'다", () => {
    expect(
      getResultStatusMessage({
        ...IDLE,
        job: job({ status: "succeeded", completedCount: 2, images: [{ assetId: "a" }, { assetId: "b" }] }),
      }),
    ).toEqual({ status: "2장 생성 완료", srSuffix: "", isInProgress: false });
  });

  it("부분 차단이면 완료 문구와 차단 문장을 한 번에 읽힌다", () => {
    expect(
      getResultStatusMessage({
        ...IDLE,
        job: job({
          status: "succeeded",
          completedCount: 1,
          images: [{ assetId: "a" }],
          blockedCount: 1,
          blockedReason: "image",
        }),
      }),
    ).toEqual({
      status: "1장 생성 완료",
      srSuffix: " 1장은 운영 정책에 따라 표시하지 않았어요.",
      isInProgress: false,
    });
  });

  it("실패한 잡은 진행 문구를 비운다(실패는 alert 가 알린다)", () => {
    expect(
      getResultStatusMessage({ ...IDLE, job: job({ status: "failed", completedCount: 1, images: [] }) }),
    ).toEqual({ status: "", srSuffix: "", isInProgress: false });
  });

  it("폴링 오류면 직전 진행 문구를 비운다", () => {
    expect(
      getResultStatusMessage({
        ...IDLE,
        hasPollError: true,
        job: job({ completedCount: 1, images: [{ assetId: "a" }] }),
      }),
    ).toEqual({ status: "", srSuffix: "", isInProgress: false });
  });

  it("폴링 오류여도 이미 받은 완료 결과가 있으면 완료 문구를 지킨다", () => {
    expect(
      getResultStatusMessage({
        ...IDLE,
        hasPollError: true,
        job: job({ status: "succeeded", completedCount: 2, images: [{ assetId: "a" }, { assetId: "b" }] }),
      }).status,
    ).toBe("2장 생성 완료");
  });
});
