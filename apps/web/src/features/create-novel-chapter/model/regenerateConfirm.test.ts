import { describe, expect, it } from "vitest";

import { toRegenerateConfirmDescription } from "./regenerateConfirm";

describe("toRegenerateConfirmDescription", () => {
  it("적용하지 않은 수정안이 없으면 다시 쓴다는 것만 말한다", () => {
    expect(toRegenerateConfirmDescription(false)).toBe("같은 대화로 이 장을 새로 써요. 지금 글은 이력에 남아요.");
  });

  it("그 장에 적용하지 않은 수정안이 있으면 사라지고 클로버가 돌아오지 않는다고 덧붙인다", () => {
    expect(toRegenerateConfirmDescription(true)).toBe(
      "같은 대화로 이 장을 새로 써요. 지금 글은 이력에 남아요. 다시 만들면 이 장에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.",
    );
  });
});
