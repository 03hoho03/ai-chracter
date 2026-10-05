import { describe, expect, it } from "vitest";

import { isProfileDestinationVisible } from "./profileDestinationVisibility";

describe("isProfileDestinationVisible", () => {
  it("내 소설은 소설화가 열린 계정에만 보인다", () => {
    expect(isProfileDestinationVisible("novels", [])).toBe(false);
    expect(isProfileDestinationVisible("novels", ["novelize"])).toBe(true);
  });

  it("기능에 딸리지 않은 목적지는 허용 기능과 무관하게 보인다", () => {
    expect(isProfileDestinationVisible("chats", [])).toBe(true);
    expect(isProfileDestinationVisible("mypage", [])).toBe(true);
  });
});
