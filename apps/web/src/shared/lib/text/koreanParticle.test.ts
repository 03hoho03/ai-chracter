import { describe, expect, it } from "vitest";

import { koreanParticle } from "./koreanParticle";

describe("koreanParticle", () => {
  it.each([
    ["15화까지", "으로/로", "로"],
    ["첫 저장", "으로/로", "으로"],
    ["서울", "으로/로", "로"],
    ["민재", "을/를", "를"],
    ["도윤", "을/를", "을"],
    ["마감 전 정리", "을/를", "를"],
    ["C2 첫 저장", "을/를", "을"],
    ["하린", "이/가", "이"],
    ["서진", "과/와", "과"],
    ["세빈", "은/는", "은"],
  ] as const)("%s 뒤 %s → %s", (word, particle, expected) => {
    expect(koreanParticle(word, particle)).toBe(expected);
  });

  it.each(["Alex", "v2", ""])("한글 음절로 끝나지 않는 %j 는 두 꼴을 함께 적는다", (word) => {
    expect(koreanParticle(word, "을/를")).toBe("을(를)");
    expect(koreanParticle(word, "으로/로")).toBe("으로(로)");
  });
});
