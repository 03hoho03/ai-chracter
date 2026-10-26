import { describe, expect, it } from "vitest";

import { cloverHubSearchSchema } from "./cloverHubSearch";
import { getReturnPlacement, parseReturnTo, returnLinkLabel } from "./returnTo";

describe("parseReturnTo", () => {
  it("이 사이트 안의 경로는 쿼리·해시까지 그대로 받는다", () => {
    expect(parseReturnTo("/chat/room-1")).toBe("/chat/room-1");
    expect(parseReturnTo("/webnovels/n1/episodes/c1?page=2#top")).toBe("/webnovels/n1/episodes/c1?page=2#top");
  });

  // 상대 URL 로 해석되는 순간 다른 호스트로 가는 모양들이다 — 결제를 마친 사람을 외부로 보내면 안 된다.
  it.each([
    ["스킴이 붙은 주소", "https://evil.example"],
    ["프로토콜 상대 주소", "//evil.example"],
    ["슬래시 뒤 역슬래시", "/\\evil.example"],
    ["역슬래시 두 개", "\\\\evil.example"],
    ["경로 중간의 역슬래시", "/chat/\\evil"],
    ["탭이 낀 주소", "/\t/evil.example"],
    ["개행이 낀 주소", "/chat\n/x"],
    ["NUL", "/chat\u0000"],
    ["DEL", "/chat\u007f"],
    ["슬래시로 시작하지 않는 경로", "chat/room-1"],
    ["javascript 스킴", "javascript:alert(1)"],
  ])("%s는 받지 않는다", (_label, value) => {
    expect(parseReturnTo(value)).toBeUndefined();
  });

  it("비어 있거나 문자열이 아니면 받지 않는다", () => {
    expect(parseReturnTo("")).toBeUndefined();
    expect(parseReturnTo(undefined)).toBeUndefined();
    expect(parseReturnTo(42)).toBeUndefined();
  });

  // 충전 화면으로 돌아가는 "돌아가기"는 같은 화면을 다시 그릴 뿐이다.
  it.each(["/clover", "/clover/", "/clover?product=lite", "/clover#x", "/clover/history", "/clover/pricing"])(
    "충전 화면 자신(%s)은 받지 않는다",
    (value) => {
      expect(parseReturnTo(value)).toBeUndefined();
    },
  );

  it("충전 화면과 이름만 비슷한 경로는 받는다", () => {
    expect(parseReturnTo("/clovers")).toBe("/clovers");
  });
});

describe("returnLinkLabel", () => {
  it("채팅 방이면 대화로, 그 밖이면 이전 화면으로 돌아간다고 말한다", () => {
    expect(returnLinkLabel("/chat/room-1")).toBe("대화로 돌아가기");
    expect(returnLinkLabel("/webnovels/n1/episodes/c1")).toBe("이전 화면으로 돌아가기");
    expect(returnLinkLabel("/chats")).toBe("이전 화면으로 돌아가기");
  });
});

describe("getReturnPlacement", () => {
  it("복귀 주소가 없으면 어디에도 두지 않는다", () => {
    expect(getReturnPlacement(null, undefined)).toEqual({ head: false, solid: false });
    expect(getReturnPlacement("paid", undefined)).toEqual({ head: false, solid: false });
  });

  it("결제 전·미완료·확인 중·문제에는 머리의 텍스트 링크만 둔다", () => {
    for (const result of [null, "notCompleted", "checking", "problem"] as const) {
      expect(getReturnPlacement(result, "/chat/r")).toEqual({ head: true, solid: false });
    }
  });

  // 같은 목적지를 두 번 두지 않는다 — 성공 뒤에는 결과 블록의 솔리드 버튼이 그 몫이다.
  it("충전에 성공하면 머리 링크를 거두고 결과 블록의 솔리드 버튼 하나로 바꾼다", () => {
    expect(getReturnPlacement("paid", "/chat/r")).toEqual({ head: false, solid: true });
  });
});

describe("cloverHubSearchSchema 의 복귀 주소", () => {
  it("안전한 복귀 주소는 상품·결제 결과와 함께 받는다", () => {
    expect(cloverHubSearchSchema.parse({ returnTo: "/chat/r", product: "lite", paymentId: "pay_1" })).toEqual({
      returnTo: "/chat/r",
      product: "lite",
      paymentId: "pay_1",
    });
  });

  // 어긋난 복귀 주소 때문에 화면이 열리지 않으면 안 된다 — 그 값만 버린다.
  it("어긋난 복귀 주소는 버리고 나머지는 그대로 읽는다", () => {
    expect(cloverHubSearchSchema.parse({ returnTo: "//evil.example", product: "lite" })).toEqual({ product: "lite" });
    expect(cloverHubSearchSchema.parse({ returnTo: "/clover" })).toEqual({});
  });
});
