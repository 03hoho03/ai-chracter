import { describe, expect, it } from "vitest";

import { compareMessageKeys, toMessageKey } from "./messageKey";

function key(createdAt: string, id: string) {
  const parsed = toMessageKey(createdAt, id);
  if (parsed === undefined) throw new Error(`키를 풀지 못했다: ${createdAt}`);
  return parsed;
}

describe("toMessageKey · compareMessageKeys", () => {
  // 서버는 마이크로초가 0 이면 소수부를 빼고 싣는다 — 글자로 비교하면 `Z` 가 `.` 보다 뒤라 순서가 뒤집힌다.
  it("소수부가 빠진 시각이 같은 초의 소수부 있는 시각보다 앞이다", () => {
    const whole = key("2026-10-24T01:02:03Z", "b");
    const fraction = key("2026-10-24T01:02:03.000005Z", "a");
    expect("2026-10-24T01:02:03Z" > "2026-10-24T01:02:03.000005Z").toBe(true);
    expect(compareMessageKeys(whole, fraction)).toBeLessThan(0);
    expect(compareMessageKeys(fraction, whole)).toBeGreaterThan(0);
  });

  // JS Date 는 밀리초까지라 같은 밀리초 안의 마이크로초 차이를 잃는다.
  it("같은 밀리초 안의 마이크로초 차이도 가른다", () => {
    expect(compareMessageKeys(key("2026-10-24T01:02:03.000001Z", "z"), key("2026-10-24T01:02:03.000002Z", "a"))).toBeLessThan(0);
  });

  it("소수부 자릿수가 달라도 같은 값이면 시각이 같고, 그때는 id 글자 순이다", () => {
    expect(compareMessageKeys(key("2026-10-24T01:02:03.5Z", "a"), key("2026-10-24T01:02:03.500000Z", "a"))).toBe(0);
    expect(compareMessageKeys(key("2026-10-24T01:02:03.5Z", "0f"), key("2026-10-24T01:02:03.500000Z", "a0"))).toBeLessThan(0);
  });

  it("시간대 오프셋을 반영한다", () => {
    expect(compareMessageKeys(key("2026-10-24T10:00:00+09:00", "b"), key("2026-10-24T01:00:00.000001Z", "a"))).toBeLessThan(0);
    expect(compareMessageKeys(key("2026-10-24T10:00:00+09:00", "a"), key("2026-10-24T01:00:00Z", "a"))).toBe(0);
  });

  it("풀 수 없는 글자나 빈 값은 키가 없다", () => {
    expect(toMessageKey(undefined, "a")).toBeUndefined();
    expect(toMessageKey(null, "a")).toBeUndefined();
    expect(toMessageKey("어제", "a")).toBeUndefined();
    expect(toMessageKey("2026-13-45T99:00:00Z", "a")).toBeUndefined();
  });
});
