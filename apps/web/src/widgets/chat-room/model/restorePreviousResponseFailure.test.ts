import { describe, expect, it } from "vitest";

import { toRestorePreviousResponseFailure } from "./restorePreviousResponseFailure";

describe("toRestorePreviousResponseFailure", () => {
  it("되돌릴 답이 없어졌으면 대화가 바뀌었다고 알리고 방을 다시 받는다", () => {
    expect(
      toRestorePreviousResponseFailure({ status: 409, detail: { code: "PREVIOUS_RESPONSE_UNAVAILABLE" }, message: "x" }),
    ).toEqual({ message: "방금 전 답변으로 돌아갈 수 없어요. 그 사이 대화가 바뀌었어요.", refetchRoom: true });
  });

  it("앞 턴이 돌고 있으면 끝난 뒤 다시 하라고만 하고 방은 다시 받지 않는다", () => {
    expect(
      toRestorePreviousResponseFailure({ status: 409, detail: { code: "CHAT_TURN_IN_PROGRESS" }, message: "x" }),
    ).toEqual({ message: "아직 앞의 응답을 만들고 있어요 · 끝나면 다시 해 주세요", refetchRoom: false });
  });

  it("재동의 403 은 전역 처리에 맡기고 아무 문구도 내지 않는다", () => {
    expect(
      toRestorePreviousResponseFailure({ status: 403, detail: { code: "LEGAL_RECONSENT_REQUIRED" }, message: "x" }),
    ).toEqual({ message: undefined, refetchRoom: false });
  });

  it("방이 없으면 대화방을 찾을 수 없다고 한다", () => {
    expect(toRestorePreviousResponseFailure({ status: 404, detail: "Chat room not found", message: "x" })).toEqual({
      message: "대화방을 찾을 수 없어요.",
      refetchRoom: false,
    });
  });

  it("다른 409 code·서버 오류·네트워크 오류는 일반 실패 문구이고 방을 다시 받지 않는다", () => {
    const generic = { message: "답변을 되돌리지 못했어요. 잠시 후 다시 시도해주세요.", refetchRoom: false };
    expect(toRestorePreviousResponseFailure({ status: 409, detail: { code: "OTHER" }, message: "x" })).toEqual(generic);
    expect(toRestorePreviousResponseFailure({ status: 409, detail: "Conflict", message: "x" })).toEqual(generic);
    expect(toRestorePreviousResponseFailure({ status: 500, detail: undefined, message: "x" })).toEqual(generic);
    expect(toRestorePreviousResponseFailure(new Error("network"))).toEqual(generic);
  });

  it("정지 403 은 재동의가 아니므로 일반 실패 문구다", () => {
    expect(toRestorePreviousResponseFailure({ status: 403, detail: "Account suspended", message: "x" }).message).toBe(
      "답변을 되돌리지 못했어요. 잠시 후 다시 시도해주세요.",
    );
  });
});
