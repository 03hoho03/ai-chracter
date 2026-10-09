import { describe, expect, it } from "vitest";

import { toNextStatementsCursor, toStatementsLoadMoreRecovery } from "./statementsCursor";

function apiError(status: number, detail: unknown) {
  return { status, detail, message: "" };
}

describe("toNextStatementsCursor", () => {
  it("서버가 다음 cursor 를 주면 그대로 넘긴다", () => {
    expect(toNextStatementsCursor({ items: [], nextCursor: "abc" })).toBe("abc");
  });

  // null 을 그대로 넘기면 무한 쿼리가 다음 페이지가 있다고 보고 "더 보기"가 끝까지 남는다.
  it("마지막 페이지(null)는 다음 페이지 없음(undefined)이다", () => {
    expect(toNextStatementsCursor({ items: [], nextCursor: null })).toBeUndefined();
  });
});

describe("toStatementsLoadMoreRecovery", () => {
  it("서버가 cursor 를 읽지 못했으면 처음부터 다시 읽는다", () => {
    expect(toStatementsLoadMoreRecovery(apiError(422, { code: "CREATOR_PAYOUT_CURSOR_INVALID" }))).toBe("restart");
  });

  it("다른 실패는 불러온 내역을 두고 다시 시도하게 한다", () => {
    expect(toStatementsLoadMoreRecovery(apiError(500, undefined))).toBe("keep");
    expect(toStatementsLoadMoreRecovery(apiError(422, { code: "OTHER" }))).toBe("keep");
    expect(toStatementsLoadMoreRecovery(apiError(503, { code: "CREATOR_PAYOUT_UNAVAILABLE" }))).toBe("keep");
    expect(toStatementsLoadMoreRecovery(new Error("network"))).toBe("keep");
  });
});
