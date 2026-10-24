import { describe, expect, it } from "vitest";

import { toDeletedMessageStatRewind } from "./deleteMessageResponse";

describe("toDeletedMessageStatRewind", () => {
  it("reads how the server rewound the stats", () => {
    expect(toDeletedMessageStatRewind({ statRewind: "rewound" })).toBe("rewound");
    expect(toDeletedMessageStatRewind({ statRewind: "kept" })).toBe("kept");
    expect(toDeletedMessageStatRewind({ statRewind: "partial" })).toBe("partial");
  });

  it("is nothing when the server had nothing to tell", () => {
    expect(toDeletedMessageStatRewind({ statRewind: null })).toBeUndefined();
  });

  // 스탯을 되돌리기 전의 서버는 본문 없는 204 를 준다 — 화면이 그 서버와 먼저 만나도 삭제는 그대로 성공해야 한다.
  it("is nothing for the empty body of a server that answers 204", () => {
    expect(toDeletedMessageStatRewind("")).toBeUndefined();
    expect(toDeletedMessageStatRewind(undefined)).toBeUndefined();
  });

  it("ignores a value it does not know instead of failing the delete", () => {
    expect(toDeletedMessageStatRewind({ statRewind: "someday" })).toBeUndefined();
  });
});
