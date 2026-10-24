import { describe, expect, it } from "vitest";

import { toCurrentPlanStep } from "./planStep";

// 단계 줄의 현재 단계 — 앞 단계를 승인해야 다음 단계가 이어진다(0 담을 대화, 1 전체 구성안, 2 화별 장면·원고).
describe("구성 모드 현재 단계", () => {
  it("담을 대화를 승인하지 않았거나 승인 뒤 고친 초안이 있으면 담을 대화다", () => {
    expect(toCurrentPlanStep({ selection: "unsaved", outline: undefined })).toBe(0);
    expect(toCurrentPlanStep({ selection: "draft", outline: "approved" })).toBe(0);
  });

  it("담을 대화를 승인했으면 구성안을 승인할 때까지 전체 구성안이다", () => {
    expect(toCurrentPlanStep({ selection: "approved", outline: undefined })).toBe(1);
    expect(toCurrentPlanStep({ selection: "approved", outline: "draft" })).toBe(1);
  });

  it("구성안을 승인했으면 화별 장면·원고다", () => {
    expect(toCurrentPlanStep({ selection: "approved", outline: "approved" })).toBe(2);
  });

  // 방이 지워진 소설은 담을 대화를 읽지 않는다(서버가 막는다) — 구성안이 있으면 그것으로 정한다.
  it("담을 대화 상태를 모르면 구성안으로 정하고, 둘 다 없으면 담을 대화다", () => {
    expect(toCurrentPlanStep({ selection: undefined, outline: undefined })).toBe(0);
    expect(toCurrentPlanStep({ selection: undefined, outline: "draft" })).toBe(1);
    expect(toCurrentPlanStep({ selection: undefined, outline: "approved" })).toBe(2);
  });
});
