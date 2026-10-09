import { describe, expect, it } from "vitest";

import { HASHTAG_TOO_LONG_MESSAGE, MAX_HASHTAG_LENGTH } from "./builderLimits";
import { HASHTAG_DUPLICATE_MESSAGE, hashtagRefusal, normalizeHashtag } from "./hashtag";

describe("normalizeHashtag", () => {
  it.each([
    ["#판타지", "판타지"],
    ["＃판타지", "판타지"],
    ["  #판타지  ", "판타지"],
    ["##판타지", "판타지"],
    ["# 판타지", "판타지"],
    ["판타지 ", "판타지"],
  ])("turns %j into %j", (input, expected) => {
    expect(normalizeHashtag(input)).toBe(expected);
  });

  it("keeps a # that is not at the front", () => {
    expect(normalizeHashtag("C#")).toBe("C#");
  });

  it("leaves nothing for a lone #", () => {
    expect(normalizeHashtag(" # ")).toBe("");
  });
});

describe("hashtagRefusal", () => {
  it("accepts a new tag", () => {
    expect(hashtagRefusal("로맨스", ["판타지"])).toBeUndefined();
  });

  it("refuses a tag that differs only in letter case", () => {
    expect(hashtagRefusal("fantasy", ["Fantasy"])).toBe(HASHTAG_DUPLICATE_MESSAGE);
    // 새 태그 쪽도 접어야 한다 — 이미 있는 쪽만 접으면 대문자로 쓴 새 태그가 빠져나간다.
    expect(hashtagRefusal("FANTASY", ["Fantasy"])).toBe(HASHTAG_DUPLICATE_MESSAGE);
  });

  it("treats a saved tag that still has its # as the same tag", () => {
    expect(hashtagRefusal("판타지", ["#판타지"])).toBe(HASHTAG_DUPLICATE_MESSAGE);
  });

  it("refuses a tag over the length limit, counting emoji once", () => {
    expect(hashtagRefusal("😀".repeat(MAX_HASHTAG_LENGTH), [])).toBeUndefined();
    expect(hashtagRefusal("가".repeat(MAX_HASHTAG_LENGTH + 1), [])).toBe(HASHTAG_TOO_LONG_MESSAGE);
  });
});
