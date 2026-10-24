import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  isProtagonistNameRequiredError,
  NOVEL_ROOM_GONE_MESSAGE,
  toNovelActionError,
  toNovelJobFailureMessage,
  toStalePatchIds,
} from "./novelActionError";

function apiError(status: number, detail: string | Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, message: "x", detail });
}

/** 서버 소설 라우트가 `detail.code` 로 내는 코드 전부와 그 상태. 429 둘은 아래에서 따로 본다. */
const SERVER_CODES: [number, string][] = [
  [403, "NOVELIZE_NOT_ALLOWED"],
  [403, "NOVEL_MODEL_NOT_ALLOWED"],
  [403, "CONTENT_RESTRICTED"],
  [403, "CONTENT_NOVELIZE_FORBIDDEN"],
  [404, "NOVEL_NOT_FOUND"],
  [403, "NOVEL_FORBIDDEN"],
  [422, "NOVEL_CURSOR_INVALID"],
  [404, "NOVEL_JOB_NOT_FOUND"],
  [404, "NOVEL_CHAPTER_NOT_FOUND"],
  [404, "NOVEL_REVISION_NOT_FOUND"],
  [409, "NOVEL_ROOM_GONE"],
  [422, "NOVEL_PROTAGONIST_NAME_REQUIRED"],
  [409, "NOVEL_NOTHING_NEW"],
  [422, "NOVEL_CHAPTER_END_INVALID"],
  [409, "NOVEL_CHAPTER_NOT_LAST"],
  [404, "NOVEL_BATCH_NOT_FOUND"],
  [409, "NOVEL_BATCH_NOT_LAST"],
  [409, "NOVEL_BATCH_SOLD"],
  [409, "NOVEL_MODEL_INELIGIBLE"],
  [422, "NOVEL_COVER_INVALID"],
  [404, "NOVEL_CHARACTER_NOT_FOUND"],
  [409, "NOVEL_CHARACTER_NAME_TAKEN"],
  [422, "NOVEL_CHARACTER_MERGE_SELF"],
  [404, "NOVEL_SNAPSHOT_NOT_FOUND"],
  [409, "NOVEL_SNAPSHOT_LIMIT"],
  [422, "NOVEL_BOARD_LAYOUT_TOO_LARGE"],
  [422, "NOVEL_PARAGRAPH_RANGE_INVALID"],
  [409, "NOVEL_JOB_NOT_APPLICABLE"],
  [409, "NOVEL_REVISION_CONFLICT"],
  [422, "NOVEL_BLOCK_IDS_INVALID"],
  [409, "NOVEL_ILLUSTRATION_LIMIT_EXCEEDED"],
  [422, "NOVEL_ILLUSTRATION_ANCHOR_INVALID"],
  [404, "NOVEL_ILLUSTRATION_NOT_FOUND"],
  [404, "NOVEL_ILLUSTRATIONS_DISABLED"],
  [409, "NOVEL_SOURCE_CHANGED"],
  [409, "NOVEL_JOB_IN_PROGRESS"],
  [409, "NOVELIZE_PRICE_CHANGED"],
];

describe("toNovelActionError", () => {
  const fallbackMessage = toNovelActionError(apiError(500, undefined), "generate")?.message;

  it.each(SERVER_CODES)("%i %s 는 일반 실패 문구가 아니라 자기 문구를 갖는다", (status, code) => {
    const notice = toNovelActionError(apiError(status, { code }), "generate");
    expect(notice).not.toBeNull();
    expect(notice?.message).not.toBe(fallbackMessage);
  });

  it("코드마다 문구가 서로 다르다 — 표를 복사하다 한 문구가 두 코드에 붙지 않았다", () => {
    const messages = SERVER_CODES.map(([status, code]) => toNovelActionError(apiError(status, { code }), "generate")?.message);
    expect(new Set(messages).size).toBe(messages.length);
  });

  it("소설 만들기 거절 403 은 스위치를 넘기지 않으면 원작자 허락 문장, 켜짐이면 중립 문장이다", () => {
    const error = apiError(403, { code: "CONTENT_NOVELIZE_FORBIDDEN" });
    expect(toNovelActionError(error, "generate")).toEqual({
      message: "원작자가 이 작품의 소설 만들기를 허용하지 않아 새 화를 만들 수 없어요.",
      shouldRefetchNovel: false,
    });
    expect(toNovelActionError(error, "generate", { isPolicyV2Enabled: false })?.message).toBe(
      "원작자가 이 작품의 소설 만들기를 허용하지 않아 새 화를 만들 수 없어요.",
    );
    expect(toNovelActionError(error, "proposal", { isPolicyV2Enabled: true })).toEqual({
      message: "이 작품으로는 지금 새 화를 만들 수 없어요.",
      shouldRefetchNovel: false,
    });
  });

  it("직접 수정의 문단 맞춤 422 는 쓴 글을 지키고 최신 글에서 다시 고르라고 말하며 상세를 다시 받는다", () => {
    expect(toNovelActionError(apiError(422, { code: "NOVEL_BLOCK_IDS_INVALID" }), "edit")).toEqual({
      message: "문단을 맞추지 못해 저장하지 못했어요. 쓴 글을 복사해 두고 취소한 뒤 최신 글에서 다시 골라 주세요.",
      shouldRefetchNovel: true,
    });
  });

  // 삽화를 옮기거나 떼는 요청이 낡은 판을 기준으로 갔다 — 최신 판을 다시 받아야 다음 요청이 같은 409 를 되풀이하지 않는다.
  it.each(["moveIllustration", "detachIllustration", "attachIllustration", "replaceIllustration"] as const)("%s 의 판 충돌 409 는 최신 내용을 다시 받는다", (action) => {
    expect(toNovelActionError(apiError(409, { code: "NOVEL_REVISION_CONFLICT" }), action)).toEqual({
      message: "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러왔어요.",
      shouldRefetchNovel: true,
    });
  });

  it("고른 문단이 지금 판에 없으면 다시 고르라고 말하고 최신 내용을 다시 받는다", () => {
    expect(toNovelActionError(apiError(422, { code: "NOVEL_ILLUSTRATION_ANCHOR_INVALID" }), "moveIllustration")).toEqual({
      message: "고른 문단이 바뀌었어요. 최신 내용을 불러왔어요. 다시 골라 주세요.",
      shouldRefetchNovel: true,
    });
  });

  // 고른 그림을 그 출처로 쓸 수 없다(남의 것·준비 안 됨·그사이 원작 제한 등). 판은 그대로라 다시 받을 것이 없고, 다른 그림을
  // 고르면 된다.
  it.each(["attachIllustration", "replaceIllustration"] as const)(
    "%s 에 쓸 수 없는 그림이면 다른 그림을 고르라고 말하고 상세는 다시 받지 않는다",
    (action) => {
      expect(toNovelActionError(apiError(422, { code: "NOVEL_ILLUSTRATION_ASSET_INVALID" }), action)).toEqual({
        message: "이 그림은 삽화로 쓸 수 없어요. 다른 그림을 골라 주세요.",
        shouldRefetchNovel: false,
      });
    },
  );

  it("한 화의 삽화 상한에 닿았으면 떼고 다시 붙이라고 말한다", () => {
    expect(
      toNovelActionError(apiError(409, { code: "NOVEL_ILLUSTRATION_LIMIT_EXCEEDED" }), "attachIllustration"),
    ).toEqual({
      message: "한 화에는 삽화를 10장까지 넣을 수 있어요. 다른 삽화를 뗀 뒤 다시 붙여 주세요.",
      shouldRefetchNovel: true,
    });
  });

  it("삽화가 지금 판에 없으면 그사이 바뀌었다고 말하고 최신 내용을 다시 받는다", () => {
    expect(toNovelActionError(apiError(404, { code: "NOVEL_ILLUSTRATION_NOT_FOUND" }), "detachIllustration")).toEqual({
      message: "이 삽화가 그사이 바뀌었어요. 최신 내용을 불러왔어요.",
      shouldRefetchNovel: true,
    });
  });

  it("삽화 기능이 꺼졌으면 지금은 할 수 없다고 말하고 상세를 다시 받는다", () => {
    expect(toNovelActionError(apiError(404, { code: "NOVEL_ILLUSTRATIONS_DISABLED" }), "moveIllustration")).toEqual({
      message: "지금은 삽화를 넣거나 고칠 수 없어요.",
      shouldRefetchNovel: true,
    });
  });

  it.each([
    ["moveIllustration", "삽화를 옮기지 못했어요. 잠시 후 다시 시도해주세요."],
    ["detachIllustration", "삽화를 떼지 못했어요. 잠시 후 다시 시도해주세요."],
    ["attachIllustration", "삽화를 붙이지 못했어요. 잠시 후 다시 시도해주세요."],
    ["replaceIllustration", "삽화를 바꾸지 못했어요. 잠시 후 다시 시도해주세요."],
  ] as const)("%s 의 일반 실패는 무엇을 못 했는지 말한다", (action, message) => {
    expect(toNovelActionError(apiError(500, undefined), action)?.message).toBe(message);
  });

  it("판매된 마지막 묶음 409 는 지울 수 없는 이유를 말하고 상세를 다시 받는다", () => {
    expect(toNovelActionError(apiError(409, { code: "NOVEL_BATCH_SOLD" }), "deleteChapter")).toEqual({
      message: "노벨에서 소장한 회원이 있는 화라 지울 수 없어요. 소설 전체를 지우면 숨겨 둘 수 있어요.",
      shouldRefetchNovel: true,
    });
  });

  it("원문 변경 409 는 다시 만들 수 없다고 말한다", () => {
    expect(toNovelActionError(apiError(409, { code: "NOVEL_SOURCE_CHANGED" }), "regenerate")?.message).toBe(
      "원래 대화가 바뀌어 이 화는 다시 만들 수 없어요.",
    );
  });

  // 서버가 이유를 실어 주면 고른 모델이 왜 안 되는지 말한다. 다시 받은 상세가 그 모델을 비활성 + 이유로 보인다.
  it("모델 부적격 409 는 이유에 따라 문장을 고르고 상세를 다시 받는다", () => {
    const turns = toNovelActionError(apiError(409, { code: "NOVEL_MODEL_INELIGIBLE", reason: "too_many_turns" }), "regenerate");
    const episodes = toNovelActionError(
      apiError(409, { code: "NOVEL_MODEL_INELIGIBLE", reason: "too_many_episodes" }),
      "regenerate",
    );
    expect(turns?.message).toContain("대화가 길어");
    expect(episodes?.message).toContain("화가 많아");
    expect(turns?.shouldRefetchNovel).toBe(true);
    expect(episodes?.shouldRefetchNovel).toBe(true);
  });

  // 재생성도 이 코드를 받는다(상세를 받은 뒤 방이 지워진 경우) — 만들기 버튼 아래 사유 문장과 같은 문장이어야
  // 다시 만들기에서 받아도 맞는 말이다.
  it.each(["generate", "regenerate"] as const)("대화방이 지워진 409 는 %s 에서도 만들기·다시 만들기 둘 다 막혔다고 말한다", (action) => {
    expect(toNovelActionError(apiError(409, { code: "NOVEL_ROOM_GONE" }), action)?.message).toBe(NOVEL_ROOM_GONE_MESSAGE);
    expect(NOVEL_ROOM_GONE_MESSAGE).toContain("다시 만들");
  });

  it("단가가 바뀌었으면 지금 단가를 말하고 상세를 다시 받는다", () => {
    const notice = toNovelActionError(apiError(409, { code: "NOVELIZE_PRICE_CHANGED", currentCost: 25 }), "generate");
    expect(notice?.message).toContain("25개");
    expect(notice?.shouldRefetchNovel).toBe(true);
  });

  it("진행 중 작업 409 는 상세를 다시 받는다 — 다시 받은 진행 중 작업으로 폴링을 잇는다", () => {
    expect(toNovelActionError(apiError(409, { code: "NOVEL_JOB_IN_PROGRESS" }), "generate")?.shouldRefetchNovel).toBe(true);
  });

  // 행동 중에 허용이 회수되면 상세를 다시 받아야 상세 조회의 403 으로 잠김 화면에 모인다 — 다시 받지 않으면 버튼이
  // 살아 있는 화면에 문장만 남는다.
  it("소설화 허용 403 은 상세를 다시 받는다", () => {
    expect(toNovelActionError(apiError(403, { code: "NOVELIZE_NOT_ALLOWED" }), "edit")?.shouldRefetchNovel).toBe(true);
  });

  // 허용을 거둔 뒤 옛 상세의 모델 목록으로 고른 경우다 — 다시 받아야 다음 확인 화면에서 그 모델이 빠진다.
  it("상위 모델 허용 403 은 상세를 다시 받는다", () => {
    expect(toNovelActionError(apiError(403, { code: "NOVEL_MODEL_NOT_ALLOWED" }), "regenerate")?.shouldRefetchNovel).toBe(
      true,
    );
  });

  it("이름 저장 실패의 일반 문구는 이름을 말한다", () => {
    expect(toNovelActionError(apiError(500, undefined), "protagonistName")?.message).toContain("주인공 이름");
  });

  it.each([
    [404, "NOVEL_NOT_FOUND"],
    [403, "NOVELIZE_NOT_ALLOWED"],
  ])("기다려도 풀리지 않는 거부(%i %s)는 이름 저장에서도 다시 시도를 말하지 않는다", (status, code) => {
    expect(toNovelActionError(apiError(status, { code }), "protagonistName")?.message).not.toContain("잠시 후");
  });

  it("재동의 403 은 이 화면이 말하지 않는다(전역 모달이 맡는다)", () => {
    expect(toNovelActionError(apiError(403, { code: "LEGAL_RECONSENT_REQUIRED", consents: ["collection", "transfer"] }), "generate")).toBeNull();
  });

  describe("429 소설화 창", () => {
    const userLimit = apiError(429, { code: "USER_LIMIT", retryAfterSeconds: 100, window: "novelize" });
    const cloverRequired = apiError(429, { code: "CLOVER_REQUIRED", retryAfterSeconds: 0, window: "novelize" });

    it("제안의 상한은 시간당이라 자정을 말하지 않는다", () => {
      const message = toNovelActionError(userLimit, "proposal")?.message;
      expect(message).not.toContain("자정");
      expect(message).not.toBe(fallbackMessage);
    });

    it.each(["generate", "regenerate"] as const)("%s 의 상한은 하루라 자정을 말한다", (action) => {
      expect(toNovelActionError(userLimit, action)?.message).toContain("자정");
    });

    it("잔액 부족은 클로버를 말한다", () => {
      expect(toNovelActionError(cloverRequired, "generate")?.message).toContain("클로버가 부족해요");
    });

    it("소설화 창이 아닌 429 는 소설 상한 문구를 쓰지 않는다", () => {
      const other = apiError(429, { code: "USER_LIMIT", retryAfterSeconds: 10, window: "minute" });
      expect(toNovelActionError(other, "generate")?.message).toBe(fallbackMessage);
    });
  });

  describe("모르는 실패는 요청별 일반 문구로 접는다", () => {
    it("모르는 코드", () => {
      expect(toNovelActionError(apiError(409, { code: "SOMETHING_NEW" }), "generate")?.message).toBe(fallbackMessage);
    });

    it("문자열 detail(방 소유권·정지)", () => {
      expect(toNovelActionError(apiError(404, "Chat room not found"), "generate")?.message).toBe(fallbackMessage);
    });

    it("네트워크 끊김·ApiError 가 아닌 값", () => {
      expect(toNovelActionError(apiError(0, undefined), "generate")?.message).toBe(fallbackMessage);
      expect(toNovelActionError(new Error("boom"), "generate")?.message).toBe(fallbackMessage);
    });

    it("요청마다 무엇을 못 했는지가 다르다", () => {
      const proposal = toNovelActionError(apiError(500, undefined), "proposal")?.message;
      const regenerate = toNovelActionError(apiError(500, undefined), "regenerate")?.message;
      expect(proposal).not.toBe(regenerate);
    });
  });
});

describe("toNovelActionError — 여러 문단 수정", () => {
  /** 여러 문단 수정 요청·적용·버리기가 받는 새 코드(재검사 코드는 재검사 화면 몫). */
  const BLOCK_EDIT_CODES: [number, string, Record<string, unknown>][] = [
    [404, "NOVEL_MULTI_BLOCK_EDIT_DISABLED", {}],
    [422, "NOVEL_TOO_MANY_BLOCKS", { maxBlocks: 20 }],
    [422, "NOVEL_BLOCKS_NOT_IN_ONE_SCENE", {}],
    [422, "NOVEL_EDIT_INPUT_TOO_LONG", { estimatedInputChars: 130000, maxInputChars: 120000 }],
    [409, "NOVEL_PATCH_STALE", { stalePatchIds: ["p1"] }],
    [404, "NOVEL_PATCH_NOT_FOUND", {}],
    [409, "NOVEL_CHAPTER_TOO_LONG", { maxChars: 100000 }],
  ];

  it.each(BLOCK_EDIT_CODES)("%i %s 는 일반 실패 문구가 아니라 자기 문구를 갖는다", (status, code, extra) => {
    const fallbackMessage = toNovelActionError(apiError(500, undefined), "applyPatch")?.message;
    const notice = toNovelActionError(apiError(status, { code, ...extra }), "applyPatch");
    expect(notice?.message).toBeTruthy();
    expect(notice?.message).not.toBe(fallbackMessage);
  });

  it("코드마다 문구가 서로 다르다", () => {
    const messages = BLOCK_EDIT_CODES.map(
      ([status, code, extra]) => toNovelActionError(apiError(status, { code, ...extra }), "aiEdit")?.message,
    );
    expect(new Set(messages).size).toBe(messages.length);
  });

  it("상한 값은 서버가 준 수를 말한다", () => {
    expect(toNovelActionError(apiError(422, { code: "NOVEL_TOO_MANY_BLOCKS", maxBlocks: 12 }), "aiEdit")?.message).toBe(
      "한 번에 12개 문단까지 고칠 수 있어요.",
    );
    expect(toNovelActionError(apiError(409, { code: "NOVEL_CHAPTER_TOO_LONG", maxChars: 100000 }), "applyPatch")?.message).toBe(
      "적용하면 화가 100,000자를 넘어요. 다른 문단을 줄인 뒤 적용해 주세요.",
    );
  });

  it("상한 값이 없으면 수를 빼고 말한다", () => {
    expect(toNovelActionError(apiError(422, { code: "NOVEL_TOO_MANY_BLOCKS" }), "aiEdit")?.message).toBe(
      "한 번에 고칠 수 있는 문단 수를 넘었어요. 문단을 줄여 다시 골라 주세요.",
    );
  });

  it("스위치 꺼짐·장면·수정안 낡음·없음은 상세를 다시 받는다", () => {
    for (const [status, code, extra] of BLOCK_EDIT_CODES) {
      const notice = toNovelActionError(apiError(status, { code, ...extra }), "aiEdit");
      const expected = code !== "NOVEL_EDIT_INPUT_TOO_LONG" && code !== "NOVEL_CHAPTER_TOO_LONG";
      expect([code, notice?.shouldRefetchNovel]).toEqual([code, expected]);
    }
  });

  // 옛 문구는 직접 수정 저장의 말이다("쓴 글을 복사해 두고…") — AI 수정 요청에서 받으면 엉뚱한 말이 된다.
  it("AI 수정 요청의 블록 id 422 는 문단을 다시 고르라고 말한다", () => {
    expect(toNovelActionError(apiError(422, { code: "NOVEL_BLOCK_IDS_INVALID" }), "aiEdit")).toEqual({
      message: "고른 문단이 바뀌었어요. 최신 내용을 불러왔어요. 다시 골라 주세요.",
      shouldRefetchNovel: true,
    });
    expect(toNovelActionError(apiError(422, { code: "NOVEL_BLOCK_IDS_INVALID" }), "edit")?.message).toContain("쓴 글을 복사해");
  });

  it("수정안 적용·버리기의 일반 실패는 무엇을 못 했는지 말한다", () => {
    expect(toNovelActionError(apiError(500, undefined), "applyPatch")?.message).toBe(
      "수정안을 적용하지 못했어요. 잠시 후 다시 시도해주세요.",
    );
    expect(toNovelActionError(apiError(500, undefined), "dismissPatch")?.message).toBe(
      "수정안을 버리지 못했어요. 잠시 후 다시 시도해주세요.",
    );
  });

  it("버리기의 적용 불가 409 는 이미 처리됐다고 말하고, 적용에서는 옛 문구 그대로다", () => {
    expect(toNovelActionError(apiError(409, { code: "NOVEL_JOB_NOT_APPLICABLE" }), "dismissPatch")).toEqual({
      message: "이미 적용했거나 버린 수정안이에요. 최신 내용을 불러왔어요.",
      shouldRefetchNovel: true,
    });
    expect(toNovelActionError(apiError(409, { code: "NOVEL_JOB_NOT_APPLICABLE" }), "applyPatch")?.message).toBe(
      "이 수정안은 더 이상 적용할 수 없어요.",
    );
  });

  it("낡은 수정안 id 를 읽는다", () => {
    expect(toStalePatchIds(apiError(409, { code: "NOVEL_PATCH_STALE", stalePatchIds: ["p1", "p2"] }))).toEqual(["p1", "p2"]);
    expect(toStalePatchIds(apiError(409, { code: "NOVEL_JOB_NOT_APPLICABLE" }))).toEqual([]);
    expect(toStalePatchIds(new Error("x"))).toEqual([]);
  });
});

describe("isProtagonistNameRequiredError", () => {
  it("422 NOVEL_PROTAGONIST_NAME_REQUIRED 만 참이다", () => {
    expect(isProtagonistNameRequiredError(apiError(422, { code: "NOVEL_PROTAGONIST_NAME_REQUIRED" }))).toBe(true);
    expect(isProtagonistNameRequiredError(apiError(422, { code: "NOVEL_CHAPTER_END_INVALID" }))).toBe(false);
    expect(isProtagonistNameRequiredError(apiError(422, undefined))).toBe(false);
  });
});

describe("toNovelJobFailureMessage", () => {
  const base = { kind: "chapter_generate", failureReason: "llm_error", refundedAmount: 120 } as const;

  // 묶음·연쇄는 낸 금액과 돌려준 금액이 다를 수 있다 — 서버가 적은 환불액을 그대로 말한다.
  it("서버가 돌려준 클로버 수를 말한다", () => {
    expect(toNovelJobFailureMessage(base)).toBe("새 화를 만들지 못했어요. 쓴 클로버 120개는 돌려드렸어요.");
    expect(toNovelJobFailureMessage({ ...base, kind: "chain_generate", refundedAmount: 45 })).toBe(
      "남은 대화를 소설로 만들지 못했어요. 쓴 클로버 45개는 돌려드렸어요.",
    );
  });

  it("돌려준 것이 없으면 환불을 말하지 않는다", () => {
    expect(toNovelJobFailureMessage({ ...base, refundedAmount: 0 })).not.toContain("돌려드렸어요");
  });

  it("재생성이 원문 변경으로 실패하면 다시 만들 수 없다고 말한다", () => {
    expect(toNovelJobFailureMessage({ ...base, kind: "chapter_regenerate", failureReason: "source_changed" })).toContain(
      "원래 대화가 바뀌어 이 화는 다시 만들 수 없어요.",
    );
  });

  it("글 형식·화 수가 어긋난 실패는 그 사유를 말한다", () => {
    expect(toNovelJobFailureMessage({ ...base, failureReason: "malformed" })).toContain("형식");
    expect(
      toNovelJobFailureMessage({ ...base, kind: "chapter_regenerate", failureReason: "episode_count_mismatch" }),
    ).toContain("화 수");
  });

  it("안전 차단은 그 사유를 말한다", () => {
    expect(toNovelJobFailureMessage({ ...base, failureReason: "blocked" })).toContain("안전 기준");
    expect(toNovelJobFailureMessage({ ...base, failureReason: "refused" })).toContain("안전 기준");
  });
});

// 묶음 다시 검사는 무료 호출이라 시간당 상한만 있다. 같은 429(`USER_LIMIT`·`novelize`)가 화 만들기의 하루 상한과 같이 오므로
// 요청으로 가른다 — 자정을 말하면 틀린다.
describe("toNovelActionError — 묶음 다시 검사", () => {
  it("시간당 상한은 자정이 아니라 남은 분을 말하고 묶음이 그대로라고 한다", () => {
    const error = apiError(429, { code: "USER_LIMIT", retryAfterSeconds: 1500, window: "novelize" });
    expect(toNovelActionError(error, "recheckBundle")).toEqual({
      message: "다시 검사를 너무 자주 했어요. 25분 뒤에 다시 검사할 수 있어요. 묶음은 그대로예요.",
      shouldRefetchNovel: false,
    });
  });

  it("남은 시간이 1분보다 짧아도 1분이라 말한다", () => {
    const error = apiError(429, { code: "USER_LIMIT", retryAfterSeconds: 5, window: "novelize" });
    expect(toNovelActionError(error, "recheckBundle")?.message).toContain("1분 뒤");
  });

  it.each([
    [409, "NOVEL_RECHECK_NOT_NEEDED", "고친 문단이 없어 묶음째 적용하면 돼요. 최신 내용을 불러왔어요.", true],
    [503, "NOVEL_RECHECK_UNAVAILABLE", "지금 다시 검사하지 못했어요. 묶음은 그대로예요. 잠시 후 다시 해 주세요.", false],
    [409, "NOVEL_JOB_NOT_APPLICABLE", "이 묶음은 그사이 바뀌어 다시 검사하지 못했어요. 최신 내용을 불러왔어요.", true],
    [404, "NOVEL_MULTI_BLOCK_EDIT_DISABLED", "지금은 묶음을 다시 검사할 수 없어요. 함께 버릴 수 있어요.", true],
  ])("%i %s 는 다시 검사의 말로 알린다", (status, code, message, shouldRefetchNovel) => {
    expect(toNovelActionError(apiError(status, { code }), "recheckBundle")).toEqual({ message, shouldRefetchNovel });
  });

  it("다른 요청에서 받은 같은 코드의 문구는 그대로다", () => {
    expect(toNovelActionError(apiError(409, { code: "NOVEL_JOB_NOT_APPLICABLE" }), "applyPatch")?.message).toBe(
      "이 수정안은 더 이상 적용할 수 없어요.",
    );
    expect(toNovelActionError(apiError(404, { code: "NOVEL_MULTI_BLOCK_EDIT_DISABLED" }), "aiEdit")?.message).toBe(
      "지금은 여러 문단을 함께 고칠 수 없어요.",
    );
    expect(
      toNovelActionError(apiError(429, { code: "USER_LIMIT", retryAfterSeconds: 100, window: "novelize" }), "regenerate")
        ?.message,
    ).toContain("자정");
  });

  it("모르는 실패는 다시 검사의 일반 문구로 접는다", () => {
    expect(toNovelActionError(apiError(500, undefined), "recheckBundle")?.message).toBe(
      "묶음을 다시 검사하지 못했어요. 잠시 후 다시 시도해주세요.",
    );
  });
});
