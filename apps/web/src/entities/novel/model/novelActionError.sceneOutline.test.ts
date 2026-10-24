import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { NOVEL_ROOM_GONE_MESSAGE, toNovelActionError, toNovelJobFailureMessage, type NovelAction } from "./novelActionError";

function apiError(status: number, detail: Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, message: "x", detail });
}

function message(status: number, detail: Record<string, unknown> | undefined, action: NovelAction) {
  return toNovelActionError(apiError(status, detail), action)?.message;
}

describe("toNovelActionError — 화별 장면 구성안·원고", () => {
  it("전체 구성안이 없거나 그 화가 없으면 그렇게 말한다", () => {
    for (const action of ["episodeOutline", "outlineChapter"] as const) {
      expect(message(409, { code: "NOVEL_OUTLINE_REQUIRED" }, action)).toBe("전체 구성안을 먼저 승인해주세요.");
      expect(message(404, { code: "NOVEL_OUTLINE_EPISODE_NOT_FOUND" }, action)).toBe(
        "이 화가 지금 승인한 구성안에 없어요. 구성안을 새로 불러왔어요.",
      );
    }
  });

  it("원고 순서·이미 쓴 화·승인한 장면 구성안 없음", () => {
    expect(message(409, { code: "NOVEL_OUTLINE_EPISODE_OUT_OF_ORDER" }, "outlineChapter")).toBe(
      "앞 화부터 차례로 써야 해요. 앞 화 원고를 먼저 써주세요.",
    );
    expect(message(409, { code: "NOVEL_OUTLINE_EPISODE_WRITTEN" }, "outlineChapter")).toBe(
      "이 화는 이미 원고가 있어요. 구성안을 새로 불러왔어요.",
    );
    expect(message(409, { code: "NOVEL_EPISODE_OUTLINE_REQUIRED" }, "outlineChapter")).toBe(
      "장면 구성안을 승인한 뒤 원고를 쓸 수 있어요.",
    );
  });

  it("장면 구성안 낡음·다른 곳에서 고침", () => {
    for (const action of ["outlineChapter", "saveEpisodeOutline", "approveEpisodeOutline"] as const) {
      expect(message(409, { code: "NOVEL_EPISODE_OUTLINE_STALE" }, action)).toBe(
        "전체 구성안에서 이 화의 근거가 바뀌어 장면 구성안이 낡았어요. 장면 구성안을 다시 만들어주세요.",
      );
    }
    expect(message(409, { code: "NOVEL_EPISODE_OUTLINE_CONFLICT" }, "saveEpisodeOutline")).toBe(
      "다른 곳에서 장면 구성안을 고쳤어요. 새로 불러왔어요.",
    );
  });

  it("장면 구성안 저장의 편집 검증 이유마다 문장이 있다", () => {
    const expected: Record<string, string> = {
      unknown_id: "다른 곳에서 장면 구성안이 바뀌어 저장하지 못했어요. 새로 불러왔어요.",
      basis_not_found: "근거 대화 중 지워진 메시지가 있어 저장하지 못했어요. 대화와 장면 구성안을 새로 불러왔어요.",
      basis_outside_episode: "이 화의 근거 밖 대화는 장면에 넣을 수 없어요. 장면 구성안을 새로 불러왔어요.",
      basis_overlap: "두 장면이 같은 턴을 나눠 가질 수 없어요. 장면 구성안을 새로 불러왔어요.",
      basis_splits_turn: "대화 한 턴을 두 장면으로 가를 수 없어요. 장면 구성안을 새로 불러왔어요.",
      something_new: "장면 구성안을 저장하지 못했어요. 새로 불러왔어요.",
    };
    for (const [reason, text] of Object.entries(expected)) {
      expect(message(422, { code: "NOVEL_EPISODE_OUTLINE_INVALID", reason }, "saveEpisodeOutline")).toBe(text);
    }
  });

  it("옛·새 다시 만들기 라우트가 화 종류로 거절하면 상세를 다시 받는다", () => {
    const old = toNovelActionError(apiError(409, { code: "NOVEL_CHAPTER_OUTLINE_FLOW" }), "regenerate");
    expect(old).toEqual({ message: "구성안으로 쓴 화는 구성안으로 다시 만들어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true });
    const fresh = toNovelActionError(apiError(409, { code: "NOVEL_CHAPTER_NOT_OUTLINE_FLOW" }), "outlineRegenerate");
    expect(fresh).toEqual({
      message: "이 화는 대화로 바로 만든 화라 그 방식으로 다시 만들어요. 소설을 다시 불러왔어요.",
      shouldRefetchNovel: true,
    });
  });

  it("턴 상한은 원고 쓰기와 구성 흐름 다시 만들기에서 각자의 말이다", () => {
    expect(message(409, { code: "NOVEL_MODEL_INELIGIBLE", reason: "too_many_turns" }, "outlineChapter")).toBe(
      "장면이 담은 대화가 길어 고른 모델로는 원고를 쓸 수 없어요. 다른 모델을 골라주세요.",
    );
    expect(message(409, { code: "NOVEL_MODEL_INELIGIBLE", reason: "too_many_turns" }, "outlineRegenerate")).toBe(
      "대화가 길어 고른 모델로는 이 화를 다시 만들 수 없어요. 다른 모델을 골라주세요.",
    );
    // 옛 묶음 다시 만들기의 문장은 그대로다.
    expect(message(409, { code: "NOVEL_MODEL_INELIGIBLE", reason: "too_many_turns" }, "regenerate")).toBe(
      "대화가 길어 고른 모델로는 이 화들을 다시 만들 수 없어요. 다른 모델을 골라주세요.",
    );
  });

  it("방이 지워졌으면 장면 구성안은 만들거나 고칠 수 없고, 원고·다시 만들기는 화 문장이다", () => {
    for (const action of ["episodeOutline", "saveEpisodeOutline"] as const) {
      expect(message(409, { code: "NOVEL_ROOM_GONE" }, action)).toBe(
        "원래 대화방이 지워져 장면 구성안을 새로 만들거나 고칠 수 없어요.",
      );
    }
    for (const action of ["outlineChapter", "outlineRegenerate"] as const) {
      expect(message(409, { code: "NOVEL_ROOM_GONE" }, action)).toBe(NOVEL_ROOM_GONE_MESSAGE);
    }
  });

  it("그사이 다른 화가 된 근거·입력 상한", () => {
    for (const action of ["episodeOutline", "outlineChapter"] as const) {
      expect(message(422, { code: "NOVEL_SOURCE_SECTION_LOCKED" }, action)).toBe(
        "이 화가 근거로 쓴 대화 중 그사이 다른 화가 된 곳이 있어요. 담을 대화와 전체 구성안을 확인해주세요.",
      );
    }
    expect(
      message(422, { code: "NOVEL_OUTLINE_INPUT_TOO_LARGE", estimatedInputTokens: 180000, maxInputTokens: 150000 }, "episodeOutline"),
    ).toBe("이 화의 대화가 너무 길어요(한도의 120%). 전체 구성안에서 이 화를 나눈 뒤 다시 만들어주세요.");
  });

  it("모르는 실패는 액션마다 일반 문구다", () => {
    const expected: Record<string, string> = {
      episodeOutline: "장면 구성안을 만들지 못했어요. 잠시 후 다시 시도해주세요.",
      saveEpisodeOutline: "장면 구성안을 저장하지 못했어요. 잠시 후 다시 시도해주세요.",
      approveEpisodeOutline: "장면 구성안을 승인하지 못했어요. 잠시 후 다시 시도해주세요.",
      outlineChapter: "원고를 쓰지 못했어요. 잠시 후 다시 시도해주세요.",
      outlineRegenerate: "화를 다시 만들지 못했어요. 잠시 후 다시 시도해주세요.",
    };
    for (const [action, text] of Object.entries(expected)) {
      expect(message(500, undefined, action as NovelAction)).toBe(text);
    }
  });
});

describe("toNovelJobFailureMessage — 화별 장면 구성안·원고", () => {
  it("원문이 바뀐 실패는 담을 대화를 다시 확인하라고 말한다", () => {
    expect(toNovelJobFailureMessage({ kind: "episode_outline_generate", failureReason: "source_changed", refundedAmount: 40 })).toBe(
      "고른 대화가 바뀌어 장면 구성안을 만들지 못했어요. 담을 대화를 확인해 다시 승인해주세요. 쓴 클로버 40개는 돌려드렸어요.",
    );
    expect(toNovelJobFailureMessage({ kind: "outline_chapter_generate", failureReason: "source_changed", refundedAmount: 0 })).toBe(
      "고른 대화가 바뀌어 원고를 쓰지 못했어요. 담을 대화를 확인해 다시 승인해주세요.",
    );
  });

  it("다른 실패 문장은 종류 주어를 그대로 쓴다", () => {
    expect(toNovelJobFailureMessage({ kind: "outline_chapter_generate", failureReason: "malformed", refundedAmount: 80 })).toBe(
      "구성안으로 새 화를 쓰지 못했어요. AI가 쓴 글의 형식이 맞지 않았어요. 쓴 클로버 80개는 돌려드렸어요.",
    );
  });
});

describe("toNovelActionError — 구성안 승인의 턴 상한 거절", () => {
  // 화면이 화 번호를 아는 자리에서는 그 문구로 바꾸지만, 그 밖에서도 일반 실패 문구로 접히지 않는다.
  it("어느 모델로도 못 쓰는 화가 있다고 말한다", () => {
    const detail = { code: "NOVEL_OUTLINE_EPISODE_TOO_LONG", maxTurns: 45, episodes: [{ key: "k", turnCount: 48 }] };
    expect(message(409, detail, "approveOutline")).toBe(
      "어느 모델로도 원고를 쓸 수 없을 만큼 긴 화가 있어요. 나눈 뒤 승인해주세요.",
    );
  });
});
