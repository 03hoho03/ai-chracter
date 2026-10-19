import { describe, expect, it } from "vitest";

import { toNovelRefundNotificationText } from "./notification";

describe("toNovelRefundNotificationText", () => {
  it("돌려준 화와 클로버 수를 말하고 소설 제목은 넣지 않는다", () => {
    expect(toNovelRefundNotificationText({ chapterCount: 2, cloverAmount: 60 }, "deleted")).toEqual({
      title: "노벨 환급 안내",
      body: "게시자가 소장하신 화 2개를 지워, 쓰신 클로버 60개를 돌려드렸어요.",
    });
  });

  it("수를 모르면 수 없이 말한다", () => {
    expect(toNovelRefundNotificationText(null, "deleted").body).toBe("게시자가 소장하신 화를 지워, 쓰신 클로버를 돌려드렸어요.");
  });

  it.each([null, undefined, "unknown-reason"] as const)("사유가 %s 면 게시자 삭제 문장 그대로다", (reason) => {
    // 서버가 나중에 사유를 늘려도 화면은 삭제 문장으로 접는다 — 타입 밖 값을 일부러 넣는다.
    const unknown = reason as Parameters<typeof toNovelRefundNotificationText>[1];
    expect(toNovelRefundNotificationText({ chapterCount: 1, cloverAmount: 30 }, unknown).body).toBe(
      "게시자가 소장하신 화 1개를 지워, 쓰신 클로버 30개를 돌려드렸어요.",
    );
  });

  it("게시자가 탈퇴해 돌려준 것이면 탈퇴를 말한다", () => {
    expect(toNovelRefundNotificationText({ chapterCount: 3, cloverAmount: 90 }, "publisher_withdrawn").body).toBe(
      "게시자가 탈퇴해, 소장하신 화 3개에 쓰신 클로버 90개를 돌려드렸어요.",
    );
    expect(toNovelRefundNotificationText(null, "publisher_withdrawn").body).toBe(
      "게시자가 탈퇴해, 소장하신 화에 쓰신 클로버를 돌려드렸어요.",
    );
  });

  it("노벨이 이용 제한돼 돌려준 것이면 운영 정책을 말한다", () => {
    expect(toNovelRefundNotificationText({ chapterCount: 2, cloverAmount: 1200 }, "novel_restricted").body).toBe(
      "소장하신 노벨이 운영 정책에 따라 이용 제한돼, 화 2개에 쓰신 클로버 1,200개를 돌려드렸어요.",
    );
    expect(toNovelRefundNotificationText(null, "novel_restricted").body).toBe(
      "소장하신 노벨이 운영 정책에 따라 이용 제한돼, 화에 쓰신 클로버를 돌려드렸어요.",
    );
  });

  it.each(["source_restricted", "source_deleted"] as const)("원작 때문(%s)이면 제한과 삭제를 같은 문장으로 말한다", (reason) => {
    expect(toNovelRefundNotificationText({ chapterCount: 4, cloverAmount: 120 }, reason).body).toBe(
      "원작을 볼 수 없게 돼, 소장하신 화 4개에 쓰신 클로버 120개를 돌려드렸어요.",
    );
    expect(toNovelRefundNotificationText(null, reason).body).toBe("원작을 볼 수 없게 돼, 소장하신 화에 쓰신 클로버를 돌려드렸어요.");
  });
});
