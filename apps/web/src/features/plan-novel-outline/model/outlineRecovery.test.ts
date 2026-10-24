import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toOutlineRecovery } from "./outlineRecovery";

function apiError(status: number, detail: Record<string, unknown>) {
  return new ApiErrorObject({ status, message: "x", detail });
}

const NOTHING = { resetEdits: false, refetchOutline: false, refetchMessages: false, refetchPricing: false };

describe("구성안 저장·승인 거절 뒤 맞추기", () => {
  it("다른 곳에서 고쳤거나 낡았으면 고친 것을 버리고 구성안을 다시 받는다", () => {
    for (const code of ["NOVEL_OUTLINE_CONFLICT", "NOVEL_OUTLINE_STALE"]) {
      expect(toOutlineRecovery(apiError(409, { code }))).toEqual({ ...NOTHING, resetEdits: true, refetchOutline: true });
    }
  });

  it("지워진 근거 메시지는 대화도 다시 받는다", () => {
    expect(toOutlineRecovery(apiError(422, { code: "NOVEL_OUTLINE_INVALID", reason: "basis_not_found" }))).toEqual({
      ...NOTHING,
      resetEdits: true,
      refetchOutline: true,
      refetchMessages: true,
    });
  });

  it("모르는 키·담은 대화 밖은 고친 것을 버리고 다시 받는다", () => {
    for (const reason of ["unknown_key", "basis_outside_include", "something_new"]) {
      expect(toOutlineRecovery(apiError(422, { code: "NOVEL_OUTLINE_INVALID", reason }))).toEqual({
        ...NOTHING,
        resetEdits: true,
        refetchOutline: true,
      });
    }
  });

  it("화 수·겹침·턴 가르기는 고친 것을 남긴다(고쳐서 다시 저장한다)", () => {
    for (const reason of ["too_many_episodes", "basis_overlap", "basis_splits_turn"]) {
      expect(toOutlineRecovery(apiError(422, { code: "NOVEL_OUTLINE_INVALID", reason }))).toEqual(NOTHING);
    }
  });

  it("스위치가 꺼졌으면 가격을 다시 받는다", () => {
    expect(toOutlineRecovery(apiError(404, { code: "NOVEL_OUTLINE_FLOW_DISABLED" }))).toEqual({
      ...NOTHING,
      refetchPricing: true,
    });
  });

  it("그 밖의 실패는 맞출 것이 없다", () => {
    expect(toOutlineRecovery(apiError(409, { code: "NOVEL_ROOM_GONE" }))).toEqual(NOTHING);
    expect(toOutlineRecovery(new Error("network"))).toEqual(NOTHING);
  });
});

describe("어느 모델로도 못 쓰는 화가 있어 승인을 못 했을 때", () => {
  // 고친 것은 이미 저장된 판이거나 이용자가 나눌 판이라 남기고, 화마다 턴 수를 새로 받아 안내를 서버와 맞춘다.
  it("고친 것을 남기고 구성안만 다시 받는다", () => {
    expect(toOutlineRecovery(apiError(409, { code: "NOVEL_OUTLINE_EPISODE_TOO_LONG", maxTurns: 45, episodes: [] }))).toEqual({
      ...NOTHING,
      refetchOutline: true,
    });
  });
});
