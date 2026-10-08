import { describe, expect, it } from "vitest";

import { toEpisodeLabel } from "./episodeLabel";

describe("toEpisodeLabel", () => {
  it("화 번호와 제목을 잇는다", () => {
    expect(toEpisodeLabel({ ordinal: 4, title: "두 번째 계산" })).toBe("4화. 두 번째 계산");
  });

  it("제목이 없으면 번호만", () => {
    expect(toEpisodeLabel({ ordinal: 4, title: null })).toBe("4화");
  });
});
