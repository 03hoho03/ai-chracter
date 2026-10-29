import { describe, expect, it } from "vitest";

import { formatCloverExpiryNotice } from "./cloverExpiryNotice";

/** 이 고지는 환불정책 게시본의 같은 사실과 짝이라 문장을 글자 그대로 고정한다 — 한 글자라도 바뀌면 게시본과 함께
 * 고치라는 신호다. 출석판 스위치를 읽지 않고도 출석 클로버를 함께 말해야 한다. */
describe("formatCloverExpiryNotice", () => {
  it("미션과 출석으로 받은 클로버를 최소 보장 기간으로 말한다", () => {
    expect(formatCloverExpiryNotice()).toBe("미션과 출석으로 받은 클로버는 받은 날부터 7일 동안 쓸 수 있어요.");
  });
});
