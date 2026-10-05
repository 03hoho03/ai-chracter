import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  isProtagonistNameRequiredError,
  NOVEL_ROOM_GONE_MESSAGE,
  toNovelActionError,
  toNovelJobFailureMessage,
} from "./novelActionError";

function apiError(status: number, detail: string | Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, message: "x", detail });
}

/** 서버 소설 라우트가 `detail.code` 로 내는 코드 전부와 그 상태. 429 둘은 아래에서 따로 본다. */
const SERVER_CODES: [number, string][] = [
  [403, "NOVELIZE_NOT_ALLOWED"],
  [403, "CONTENT_RESTRICTED"],
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
  [422, "NOVEL_PARAGRAPH_RANGE_INVALID"],
  [409, "NOVEL_JOB_NOT_APPLICABLE"],
  [409, "NOVEL_REVISION_CONFLICT"],
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

  it("원문 변경 409 는 다시 만들 수 없다고 말한다", () => {
    expect(toNovelActionError(apiError(409, { code: "NOVEL_SOURCE_CHANGED" }), "regenerate")?.message).toBe(
      "원래 대화가 바뀌어 이 장은 다시 만들 수 없어요.",
    );
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

  it("재동의 403 은 이 화면이 말하지 않는다(전역 모달이 맡는다)", () => {
    expect(toNovelActionError(apiError(403, { code: "LEGAL_RECONSENT_REQUIRED", kinds: ["privacy"] }), "generate")).toBeNull();
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

describe("isProtagonistNameRequiredError", () => {
  it("422 NOVEL_PROTAGONIST_NAME_REQUIRED 만 참이다", () => {
    expect(isProtagonistNameRequiredError(apiError(422, { code: "NOVEL_PROTAGONIST_NAME_REQUIRED" }))).toBe(true);
    expect(isProtagonistNameRequiredError(apiError(422, { code: "NOVEL_CHAPTER_END_INVALID" }))).toBe(false);
    expect(isProtagonistNameRequiredError(apiError(422, undefined))).toBe(false);
  });
});

describe("toNovelJobFailureMessage", () => {
  const base = { kind: "chapter_generate", failureReason: "llm_error", refunded: true, chargedAmount: 20 } as const;

  it("환불한 클로버 수를 말한다", () => {
    expect(toNovelJobFailureMessage(base)).toBe("새 장을 만들지 못했어요. 쓴 클로버 20개는 돌려드렸어요.");
  });

  it("환불하지 않았으면 환불을 말하지 않는다", () => {
    expect(toNovelJobFailureMessage({ ...base, refunded: false })).not.toContain("돌려드렸어요");
  });

  it("재생성이 원문 변경으로 실패하면 다시 만들 수 없다고 말한다", () => {
    expect(toNovelJobFailureMessage({ ...base, kind: "chapter_regenerate", failureReason: "source_changed" })).toContain(
      "원래 대화가 바뀌어 이 장은 다시 만들 수 없어요.",
    );
  });

  it("안전 차단은 그 사유를 말한다", () => {
    expect(toNovelJobFailureMessage({ ...base, failureReason: "blocked" })).toContain("안전 기준");
    expect(toNovelJobFailureMessage({ ...base, failureReason: "refused" })).toContain("안전 기준");
  });
});
