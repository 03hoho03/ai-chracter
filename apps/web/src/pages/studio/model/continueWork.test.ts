import { describe, expect, it } from "vitest";

import { pickContinueWork } from "./continueWork";
import { makeContentWork, makeNovelWork } from "./workFixtures";

const settled = makeContentWork({ id: "settled", hasPublished: true, visibility: "public" });
const draft = makeContentWork({ id: "draft", hasPublished: false });
const changed = makeContentWork({ id: "changed", hasPublished: true, hasUnpublishedChanges: true });
const restrictedChanged = makeContentWork({
  id: "restricted",
  hasPublished: true,
  hasUnpublishedChanges: true,
  moderationStatus: "restricted",
});
const novel = makeNovelWork({ id: "novel" });

describe("pickContinueWork", () => {
  it("목록 순서에서 첫 번째 끝나지 않은 일을 고른다", () => {
    expect(pickContinueWork([settled, draft, changed], true)?.id).toBe("draft");
    expect(pickContinueWork([settled, changed, draft], true)?.id).toBe("changed");
  });

  it("수정본 없는 발행작만 있으면 고를 것이 없다", () => {
    expect(pickContinueWork([settled], true)).toBeUndefined();
    expect(pickContinueWork([], true)).toBeUndefined();
  });

  it("이용제한 작품은 수정본이 있어도 건너뛴다", () => {
    expect(pickContinueWork([restrictedChanged, draft], true)?.id).toBe("draft");
    expect(pickContinueWork([restrictedChanged], true)).toBeUndefined();
  });

  it("소설은 소설 영역이 열린 계정에서만 고른다", () => {
    expect(pickContinueWork([settled, novel, draft], true)?.id).toBe("novel");
    expect(pickContinueWork([settled, novel, draft], false)?.id).toBe("draft");
  });
});
