import { describe, expect, it } from "vitest";

import { toWebnovelsView } from "./webnovelsView";

describe("toWebnovelsView", () => {
  it("스위치가 켜지면 소장 칩이 생기고 소장 주소는 소장 목록이다", () => {
    expect(toWebnovelsView("owned", { novelPublicPolicyV2Enabled: true })).toEqual({
      shown: "owned",
      chips: ["latest", "popular", "owned"],
      chipsLabel: "목록",
    });
  });

  it.each([{ novelPublicPolicyV2Enabled: false }, {}])("스위치가 꺼졌거나 값이 없으면 칩은 지금 둘이고 소장 주소도 최신순이다 (%#)", (pricing) => {
    expect(toWebnovelsView("owned", pricing)).toEqual({ shown: "latest", chips: ["latest", "popular"], chipsLabel: "정렬" });
    expect(toWebnovelsView("popular", pricing)).toEqual({ shown: "popular", chips: ["latest", "popular"], chipsLabel: "정렬" });
  });

  it("가격 응답을 받는 중이면 주소를 믿되 소장 칩은 아직 없다", () => {
    expect(toWebnovelsView("owned", undefined)).toEqual({ shown: "owned", chips: ["latest", "popular"], chipsLabel: "정렬" });
  });
});
