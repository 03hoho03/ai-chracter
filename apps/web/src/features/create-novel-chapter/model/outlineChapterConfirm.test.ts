import { describe, expect, it } from "vitest";

import { toOutlineChapterConfirm } from "./outlineChapterConfirm";

describe("구성안으로 쓰는 화의 원고 확인 창 글", () => {
  it("제목·설명·실행 버튼은 지금 그대로다", () => {
    const confirm = toOutlineChapterConfirm("「그날 밤」 화");
    expect(confirm.title).toBe("원고를 쓸까요?");
    expect(confirm.description).toBe("「그날 밤」 화를 승인한 장면 구성안대로 써요. 다 쓰면 보드에 새 화로 놓여요.");
    expect(confirm.confirmLabel).toBe("원고 쓰기");
  });

  // 원고는 그 화 장면 근거의 원문을 기억해 두고, 다시 만들 때 원문이 다르면 거절한다. 다시 생성한 답은 옛 답을 지우고 그 뒤 시각에
  // 들어가므로 이 화가 아니라 담을 대화의 고른 뒤 이어진 대화로 보인다 — 대화로 바로 만든 화처럼 다음 화에 저절로 담기지 않는다.
  it("원고를 쓴 뒤 마지막 답을 바꾸면 생기는 일을 금액 줄 아래 한 줄로 말한다", () => {
    const { note } = toOutlineChapterConfirm("이 화");
    expect(note).toBe(
      "원고를 쓴 뒤 이 화에 담긴 마지막 답을 다시 생성하거나 방금 전 답변으로 돌리면 이 화는 다시 만들 수 없어요. 다시 생성한 답은 담을 대화에 고른 뒤 이어진 대화로 나타나요.",
    );
    expect(note).not.toContain("다음 화에 담겨요");
  });
});
