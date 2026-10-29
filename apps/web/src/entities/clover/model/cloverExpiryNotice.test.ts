import { describe, expect, it } from "vitest";

import { formatCloverExpiryNotice } from "./cloverExpiryNotice";

/** 이 고지는 환불정책 게시본의 같은 사실과 짝이다. 꺼진 동안은 지금 게시본, 켜지면 출석판과 같은 순간 시행되는 새 게시본의
 * 짝이라 두 문장을 글자 그대로 고정한다 — 한 글자라도 바뀌면 게시본과 함께 고치라는 신호다. */
describe("formatCloverExpiryNotice", () => {
  it("출석판이 꺼져 있으면 지금 문장 그대로다", () => {
    expect(formatCloverExpiryNotice(false)).toBe("미션으로 받은 클로버는 지급일 자정 기준으로 7~8일 뒤 소멸돼요.");
  });

  it("출석판이 켜져 있으면 미션과 출석으로 받은 클로버를 최소 보장 기간으로 말한다", () => {
    expect(formatCloverExpiryNotice(true)).toBe("미션과 출석으로 받은 클로버는 받은 날부터 7일 동안 쓸 수 있어요.");
  });
});
