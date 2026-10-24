import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toEpisodeOutlineRecovery } from "./episodeRecovery";

function apiError(status: number, detail: Record<string, unknown>) {
  return new ApiErrorObject({ status, message: "x", detail });
}

const NOTHING = {
  resetEdits: false,
  refetchEpisode: false,
  refetchOutline: false,
  refetchMessages: false,
  refetchPricing: false,
};

describe("장면 구성안 저장·승인 거절 뒤 맞추기", () => {
  it("다른 곳에서 고쳤으면 고친 것을 버리고 그 화를 다시 받는다", () => {
    expect(toEpisodeOutlineRecovery(apiError(409, { code: "NOVEL_EPISODE_OUTLINE_CONFLICT" }))).toEqual({
      ...NOTHING,
      resetEdits: true,
      refetchEpisode: true,
    });
  });

  it("낡았으면 구성안도 다시 받아 화 목록의 낡음을 맞춘다", () => {
    expect(toEpisodeOutlineRecovery(apiError(409, { code: "NOVEL_EPISODE_OUTLINE_STALE" }))).toEqual({
      ...NOTHING,
      resetEdits: true,
      refetchEpisode: true,
      refetchOutline: true,
    });
  });

  it("편집 검증 거절은 근거를 고치지 않는 화면에서는 서버와 어긋난 것이라 버리고 다시 받는다", () => {
    for (const reason of ["unknown_id", "basis_outside_episode", "basis_overlap", "basis_splits_turn", "new_reason"]) {
      expect(toEpisodeOutlineRecovery(apiError(422, { code: "NOVEL_EPISODE_OUTLINE_INVALID", reason }))).toEqual({
        ...NOTHING,
        resetEdits: true,
        refetchEpisode: true,
      });
    }
    expect(toEpisodeOutlineRecovery(apiError(422, { code: "NOVEL_EPISODE_OUTLINE_INVALID", reason: "basis_not_found" }))).toEqual({
      ...NOTHING,
      resetEdits: true,
      refetchEpisode: true,
      refetchMessages: true,
    });
  });

  it("전체 구성안이 없거나 그 화가 빠졌으면 둘 다 다시 받는다", () => {
    for (const code of ["NOVEL_OUTLINE_REQUIRED", "NOVEL_OUTLINE_EPISODE_NOT_FOUND"]) {
      expect(toEpisodeOutlineRecovery(apiError(409, { code }))).toEqual({
        ...NOTHING,
        resetEdits: true,
        refetchEpisode: true,
        refetchOutline: true,
      });
    }
  });

  it("스위치가 꺼졌으면 가격을 다시 받는다", () => {
    expect(toEpisodeOutlineRecovery(apiError(404, { code: "NOVEL_OUTLINE_FLOW_DISABLED" }))).toEqual({
      ...NOTHING,
      refetchPricing: true,
    });
  });

  it("그 밖의 실패는 고친 것을 남긴다", () => {
    expect(toEpisodeOutlineRecovery(apiError(409, { code: "NOVEL_ROOM_GONE" }))).toEqual(NOTHING);
    expect(toEpisodeOutlineRecovery(new Error("network"))).toEqual(NOTHING);
  });
});
