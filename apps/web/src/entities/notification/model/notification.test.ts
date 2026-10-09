import { describe, expect, it } from "vitest";

import { toNovelRefundNotificationText } from "./notification";

describe("toNovelRefundNotificationText", () => {
  it("돌려준 화와 클로버 수를 말하고 소설 제목은 넣지 않는다", () => {
    expect(toNovelRefundNotificationText({ chapterCount: 2, cloverAmount: 60 })).toEqual({
      title: "노벨 환급 안내",
      body: "게시자가 소장하신 화 2개를 지워, 쓰신 클로버 60개를 돌려드렸어요.",
    });
  });

  it("수를 모르면 수 없이 말한다", () => {
    expect(toNovelRefundNotificationText(null).body).toBe("게시자가 소장하신 화를 지워, 쓰신 클로버를 돌려드렸어요.");
  });
});
