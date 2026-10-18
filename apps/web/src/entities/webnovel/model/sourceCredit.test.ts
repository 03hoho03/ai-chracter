import { describe, expect, it } from "vitest";

import { toSourceCredit } from "./sourceCredit";

describe("toSourceCredit", () => {
  it("원작자와 게시자가 다르면 원작자 줄을 내고 비공식 2차 창작을 붙인다", () => {
    expect(toSourceCredit({ creatorNickname: "미나", unofficial: true })).toEqual({
      creatorNickname: "미나",
      publisherIsCreator: false,
      isUnofficial: true,
    });
  });

  it("원작자가 탈퇴했으면 원작자 줄을 내지 않는다", () => {
    expect(toSourceCredit({ creatorNickname: null, unofficial: true })).toEqual({
      creatorNickname: undefined,
      publisherIsCreator: false,
      isUnofficial: true,
    });
  });

  it("원작자가 게시자 본인이면 원작자 줄 대신 게시자 줄에 원작자라고 붙이고 배지는 없다", () => {
    expect(toSourceCredit({ creatorNickname: "소라", unofficial: false })).toEqual({
      creatorNickname: undefined,
      publisherIsCreator: true,
      isUnofficial: false,
    });
  });

  it("두 칸이 없는 옛 응답이면 원작자 표기를 하나도 그리지 않는다", () => {
    const legacy: Parameters<typeof toSourceCredit>[0] = JSON.parse("{}");
    expect(toSourceCredit(legacy)).toEqual({ creatorNickname: undefined, publisherIsCreator: false, isUnofficial: false });
  });
});
