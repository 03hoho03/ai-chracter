import { describe, expect, it } from "vitest";

import { toPublisherCredit, toPublisherName, toSourceCredit, WITHDRAWN_USER_LABEL } from "./sourceCredit";

describe("toSourceCredit", () => {
  it("원작자와 게시자가 다르면 원작자 줄을 내고 파생 배지를 붙인다", () => {
    expect(toSourceCredit({ creatorNickname: "미나", unofficial: true, creatorWithdrawn: false })).toEqual({
      creator: { kind: "nickname", nickname: "미나" },
      publisherIsCreator: false,
      isUnofficial: true,
    });
  });

  it("원작자가 탈퇴했으면 원작자 줄에 탈퇴한 사용자라고 쓴다", () => {
    expect(toSourceCredit({ creatorNickname: null, unofficial: true, creatorWithdrawn: true })).toEqual({
      creator: { kind: "withdrawn" },
      publisherIsCreator: false,
      isUnofficial: true,
    });
  });

  it("이름이 비었지만 탈퇴가 아니면(원작 행 없음·닉네임 없음) 원작자 줄을 내지 않는다", () => {
    expect(toSourceCredit({ creatorNickname: null, unofficial: true, creatorWithdrawn: false })).toEqual({
      creator: undefined,
      publisherIsCreator: false,
      isUnofficial: true,
    });
  });

  it("원작자가 게시자 본인이면 원작자 줄 대신 게시자 줄에 원작자라고 붙이고 배지는 없다", () => {
    expect(toSourceCredit({ creatorNickname: "소라", unofficial: false, creatorWithdrawn: false })).toEqual({
      creator: undefined,
      publisherIsCreator: true,
      isUnofficial: false,
    });
  });

  it("원작자 본인인 게시자가 탈퇴했어도 게시자 줄에 원작자라고 붙인다(원작자 줄은 따로 없다)", () => {
    expect(toSourceCredit({ creatorNickname: null, unofficial: false, creatorWithdrawn: true })).toEqual({
      creator: undefined,
      publisherIsCreator: true,
      isUnofficial: false,
    });
  });

  it("칸이 없는 옛 응답이면 원작자 표기를 하나도 그리지 않는다", () => {
    const legacy: Parameters<typeof toSourceCredit>[0] = JSON.parse("{}");
    expect(toSourceCredit(legacy)).toEqual({ creator: undefined, publisherIsCreator: false, isUnofficial: false });
  });
});

describe("toPublisherCredit", () => {
  it("게시자가 있으면 프로필로 건다", () => {
    expect(toPublisherCredit({ publisherUserId: "u1", publisherNickname: "하루", publisherWithdrawn: false })).toEqual({
      kind: "profile",
      userId: "u1",
      nickname: "하루",
    });
  });

  it("게시자가 탈퇴했으면 글자만 쓴다(걸 회원 id 가 없다)", () => {
    expect(toPublisherCredit({ publisherUserId: null, publisherNickname: null, publisherWithdrawn: true })).toEqual({
      kind: "withdrawn",
    });
  });

  it.each([
    { publisherUserId: null, publisherNickname: "하루" },
    { publisherUserId: "u1", publisherNickname: null },
  ])("탈퇴가 아닌데 id·이름 중 하나가 비면 줄을 내지 않는다 (%o)", (partial) => {
    expect(toPublisherCredit({ ...partial, publisherWithdrawn: false })).toBeUndefined();
  });

  it("칸이 없는 옛 응답은 탈퇴로 읽지 않는다", () => {
    const legacy: Parameters<typeof toPublisherCredit>[0] = JSON.parse('{"publisherUserId":null,"publisherNickname":null}');
    expect(toPublisherCredit(legacy)).toBeUndefined();
  });
});

describe("toPublisherName", () => {
  it("탈퇴한 게시자는 탈퇴한 사용자다", () => {
    expect(toPublisherName({ publisherNickname: null, publisherWithdrawn: true })).toBe(WITHDRAWN_USER_LABEL);
    expect(WITHDRAWN_USER_LABEL).toBe("탈퇴한 사용자");
  });

  it("아니면 닉네임 그대로(없으면 null)", () => {
    expect(toPublisherName({ publisherNickname: "하루", publisherWithdrawn: false })).toBe("하루");
    expect(toPublisherName({ publisherNickname: null, publisherWithdrawn: false })).toBeNull();
  });
});
