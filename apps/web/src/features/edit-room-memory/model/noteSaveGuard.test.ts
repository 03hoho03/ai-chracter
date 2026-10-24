import { describe, expect, it } from "vitest";

import { isNoteSaveBlocked } from "./noteSaveGuard";

const IDLE = { isSavePending: false, isClearPending: false, isSubmitting: false };

describe("isNoteSaveBlocked", () => {
  it("lets [저장] through when nothing is in flight", () => {
    expect(isNoteSaveBlocked(IDLE)).toBe(false);
  });

  it("blocks while a save is in flight", () => {
    expect(isNoteSaveBlocked({ ...IDLE, isSavePending: true })).toBe(true);
  });

  // 비우기가 도는 동안 저장이 나가면 비운 결과 위에 옛 노트가 다시 저장된다.
  it("blocks while clearing the note, even though no form submit is running", () => {
    expect(isNoteSaveBlocked({ ...IDLE, isClearPending: true })).toBe(true);
  });

  it("blocks while the form is validating a submit", () => {
    expect(isNoteSaveBlocked({ ...IDLE, isSubmitting: true })).toBe(true);
  });
});
