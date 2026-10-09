import { describe, expect, it } from "vitest";

import { applyWebnovelLike } from "./applyWebnovelLike";

describe("applyWebnovelLike", () => {
  it("좋아요하면 수를 하나 올리고 취소하면 내린다", () => {
    expect(applyWebnovelLike({ liked: false, likeCount: 3 }, true)).toEqual({ liked: true, likeCount: 4 });
    expect(applyWebnovelLike({ liked: true, likeCount: 4 }, false)).toEqual({ liked: false, likeCount: 3 });
  });

  it("이미 그 값이면 수를 두 번 바꾸지 않는다", () => {
    const detail = { liked: true, likeCount: 4 };
    expect(applyWebnovelLike(detail, true)).toBe(detail);
  });

  it("수는 0 밑으로 내려가지 않는다", () => {
    expect(applyWebnovelLike({ liked: true, likeCount: 0 }, false)).toEqual({ liked: false, likeCount: 0 });
  });
});
