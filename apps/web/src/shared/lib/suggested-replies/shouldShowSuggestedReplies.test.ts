import { describe, expect, it } from "vitest";

import { shouldShowSuggestedReplies } from "./shouldShowSuggestedReplies";

const REPLIES = ["주변을 둘러본다"];

describe("shouldShowSuggestedReplies", () => {
  it("returns true when turnCount is 0, replies exist, and the user has not spoken", () => {
    expect(shouldShowSuggestedReplies(REPLIES, 0, false)).toBe(true);
  });

  it("returns false when turnCount is 1 or more even if replies exist", () => {
    expect(shouldShowSuggestedReplies(REPLIES, 1, true)).toBe(false);
    expect(shouldShowSuggestedReplies(REPLIES, 20, true)).toBe(false);
  });

  it("returns false when there are no replies even at turnCount 0", () => {
    expect(shouldShowSuggestedReplies([], 0, false)).toBe(false);
  });

  // 서버 turn_count는 성공한 턴만 센다. 사용자 메시지는 Gemini 호출 전에 커밋되지만
  // turn_count += 1은 생성 성공 후에만 실행되므로, 생성이 실패한 방은 발화가 쌓여도 0에 머문다
  // (dev DB 실측: turn_count=0인 방 38개 중 31개가 이 상태였다).
  it("returns false when generation kept failing — user has spoken but turnCount is still 0", () => {
    expect(shouldShowSuggestedReplies(REPLIES, 0, true)).toBe(false);
  });

  // turnCount는 스트림이 끝나야 오른다. 사용자 메시지는 전송 즉시 캐시에 들어가므로
  // 이 항이 첫 응답을 생성하는 구간을 덮는다.
  it("returns false while the first response is still streaming", () => {
    expect(shouldShowSuggestedReplies(REPLIES, 0, true)).toBe(false);
  });
});
