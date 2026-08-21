import { describe, expect, it } from "vitest";

import { listVisibilityTransitions, VISIBILITY_TRANSITION_COPY } from "./visibilityTransition";

describe("listVisibilityTransitions", () => {
  it("현재 공개범위는 빼고 나머지 둘만 돌려준다", () => {
    expect(listVisibilityTransitions("public")).toEqual(["link", "private"]);
    expect(listVisibilityTransitions("link")).toEqual(["public", "private"]);
    expect(listVisibilityTransitions("private")).toEqual(["public", "link"]);
  });

  it("돌려주는 모든 전환에 카피가 있다", () => {
    for (const current of ["public", "link", "private"] as const) {
      for (const target of listVisibilityTransitions(current)) {
        expect(VISIBILITY_TRANSITION_COPY[target].label).toBeTruthy();
        expect(VISIBILITY_TRANSITION_COPY[target].description).toBeTruthy();
      }
    }
  });
});
