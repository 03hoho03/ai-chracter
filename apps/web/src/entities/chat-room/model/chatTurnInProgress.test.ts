import { describe, expect, it } from "vitest";

import { CHAT_TURN_IN_PROGRESS_NOTICE, isChatTurnInProgressError } from "./chatTurnInProgress";

describe("isChatTurnInProgressError", () => {
  it("409 + {code: CHAT_TURN_IN_PROGRESS}면 true다", () => {
    expect(isChatTurnInProgressError({ status: 409, detail: { code: "CHAT_TURN_IN_PROGRESS" }, message: "x" })).toBe(true);
  });

  it("다른 409 code 와 문자열 detail 은 false다 — 기존 실패 배너로 간다", () => {
    expect(isChatTurnInProgressError({ status: 409, detail: { code: "MEMORY_VERSION_CONFLICT" }, message: "x" })).toBe(
      false,
    );
    expect(isChatTurnInProgressError({ status: 409, detail: "Conflict", message: "x" })).toBe(false);
  });

  it("같은 code 여도 409 가 아니면 false고, 오류 객체가 아니어도 false다", () => {
    expect(isChatTurnInProgressError({ status: 429, detail: { code: "CHAT_TURN_IN_PROGRESS" }, message: "x" })).toBe(
      false,
    );
    expect(isChatTurnInProgressError({ status: 500, detail: undefined, message: "x" })).toBe(false);
    expect(isChatTurnInProgressError(new Error("network"))).toBe(false);
  });

  it("안내 문구는 사실 · 다음 행동 두 토막이다", () => {
    expect(CHAT_TURN_IN_PROGRESS_NOTICE).toBe("아직 앞의 응답을 만들고 있어요 · 끝나면 다시 보내 주세요");
  });
});
