import { describe, expect, it } from "vitest";

import { toRegenerateConfirmDescription } from "./regenerateConfirm";

describe("toRegenerateConfirmDescription", () => {
  it("한 화면 다시 쓴다는 것만 말한다", () => {
    expect(toRegenerateConfirmDescription({ rangeLabel: "2화", episodeCount: 1, hasPendingAiEdits: false })).toBe(
      "같은 대화로 이 화를 새로 써요. 지금 글은 이력에 남아요.",
    );
  });

  // 3화에서 눌러도 1~3화가 함께 바뀐다 — 확인 전에 그 범위를 말하지 않으면 다른 화의 글이 몰래 바뀐다.
  it("여러 화면 함께 바뀌는 화들과 화 수가 그대로라는 것을 말한다", () => {
    expect(toRegenerateConfirmDescription({ rangeLabel: "1~3화", episodeCount: 3, hasPendingAiEdits: false })).toBe(
      "같은 대화로 함께 만든 1~3화를 모두 새로 써요. 화 수는 그대로이고 지금 글은 이력에 남아요.",
    );
  });

  it("그 화들에 적용하지 않은 수정안이 있으면 사라지고 클로버가 돌아오지 않는다고 덧붙인다", () => {
    expect(toRegenerateConfirmDescription({ rangeLabel: "2화", episodeCount: 1, hasPendingAiEdits: true })).toBe(
      "같은 대화로 이 화를 새로 써요. 지금 글은 이력에 남아요. 다시 만들면 이 화에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.",
    );
    expect(toRegenerateConfirmDescription({ rangeLabel: "1~3화", episodeCount: 3, hasPendingAiEdits: true })).toContain(
      "이 화들에서 적용하지 않은 AI 수정안",
    );
  });
});
