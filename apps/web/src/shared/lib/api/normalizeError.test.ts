import { describe, expect, it } from "vitest";

import { errorEnvelopeSchema } from "./client";

/**
 * FastAPI 에러 봉투 파싱. 이 경로는 지금까지 테스트가 0이었는데, `as` 단언이 무엇이 오든
 * 통과시켜 왔기 때문에 **깨져도 드러날 자리가 없었다**. 스키마로 바꾸면서 실제 세 모양과
 * 실패 경로를 고정한다.
 *
 * 특히 마지막 둘이 단언과 파싱이 갈리는 지점이다 — 단언은 HTML 문자열도 통과시켜
 * `detail.loc?.at(-1)`에서 터졌지만, 파싱은 `undefined`로 떨어져 폴백이 받는다.
 */
const detailOf = (data: unknown) => {
  const parsed = errorEnvelopeSchema.safeParse(data);
  return parsed.success ? parsed.data.detail : undefined;
};

describe("errorEnvelopeSchema", () => {
  it("HTTPException의 string detail을 그대로 통과시킨다", () => {
    expect(detailOf({ detail: "권한이 없어요" })).toBe("권한이 없어요");
  });

  it("422 검증 배열을 통과시키고 여분 키(type)는 흘려보낸다", () => {
    expect(detailOf({ detail: [{ loc: ["body", "email"], msg: "invalid", type: "value_error" }] })).toEqual([
      { loc: ["body", "email"], msg: "invalid" },
    ]);
  });

  it("구조화 dict(429의 retryAfterSeconds 등)를 통과시킨다", () => {
    expect(detailOf({ detail: { retryAfterSeconds: 30 } })).toEqual({ retryAfterSeconds: 30 });
  });

  it("detail이 없으면 undefined다", () => {
    expect(detailOf({})).toBeUndefined();
  });

  it("프록시가 끼워 넣은 HTML 에러 페이지는 undefined로 떨어진다", () => {
    expect(detailOf("<html>502 Bad Gateway</html>")).toBeUndefined();
  });

  it("응답 본문 자체가 없어도(네트워크 에러) undefined다", () => {
    expect(detailOf(undefined)).toBeUndefined();
  });
});
