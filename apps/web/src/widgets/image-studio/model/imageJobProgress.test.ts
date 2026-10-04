import { describe, expect, it } from "vitest";

import { isImageJobInProgress } from "./imageJobProgress";

const RUNNING = { hasSubmission: true, status: "running", hasPollError: false } as const;

// 생성 버튼을 잠글지 정하는 판정. 잠금이 풀리지 않으면 사용자는 다시 생성할 길이 없고, 너무 일찍 풀리면
// 서버의 사용자당 잡 1개 제한에 걸려 429 로 끝난다.
describe("isImageJobInProgress", () => {
  it("202 를 받은 제출이 없으면 진행 중이 아니다", () => {
    expect(isImageJobInProgress({ hasSubmission: false, status: undefined, hasPollError: false })).toBe(false);
  });

  it("202 직후 첫 응답 전(status 없음)은 진행 중이다", () => {
    expect(isImageJobInProgress({ hasSubmission: true, status: undefined, hasPollError: false })).toBe(true);
  });

  it("queued·running 은 진행 중이다", () => {
    expect(isImageJobInProgress({ ...RUNNING, status: "queued" })).toBe(true);
    expect(isImageJobInProgress(RUNNING)).toBe(true);
  });

  it("succeeded·failed 면 끝났다", () => {
    expect(isImageJobInProgress({ ...RUNNING, status: "succeeded" })).toBe(false);
    expect(isImageJobInProgress({ ...RUNNING, status: "failed" })).toBe(false);
  });

  it("폴링이 오류면 마지막 응답이 running 이어도 풀린다 — 안 풀면 잠금이 영원히 남는다", () => {
    expect(isImageJobInProgress({ ...RUNNING, hasPollError: true })).toBe(false);
    expect(isImageJobInProgress({ hasSubmission: true, status: undefined, hasPollError: true })).toBe(false);
  });
});
