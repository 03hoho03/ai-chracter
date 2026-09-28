import { describe, expect, it } from "vitest";

import { getReferenceImageError } from "./referenceImageError";

// 서버는 참조 오류 둘을 상태 코드가 아니라 고정 `detail` 문자열로 가른다 — 404와 400은 다른
// 이유(없는 경로·잘못된 비율 등)로도 오므로, 문자열만 보거나 상태만 보면 엉뚱한 실패에서 참조를
// 비운다.
describe("getReferenceImageError", () => {
  it("404와 참조 없음 문구면 not_found다", () => {
    expect(getReferenceImageError({ status: 404, detail: "reference image not found", message: "x" })).toBe(
      "not_found",
    );
  });

  it("400과 참조 꺼짐 문구면 disabled다", () => {
    expect(getReferenceImageError({ status: 400, detail: "reference image disabled", message: "x" })).toBe(
      "disabled",
    );
  });

  it.each([
    [404, "Not Found"],
    [400, "unsupported aspect ratio"],
    [400, "reference image not found"],
    [404, "reference image disabled"],
  ])("상태 %d와 문구 %s의 짝이 아니면 참조 오류가 아니다", (status, detail) => {
    expect(getReferenceImageError({ status, detail, message: "x" })).toBeUndefined();
  });

  it("API 오류가 아니면 참조 오류가 아니다", () => {
    expect(getReferenceImageError(new Error("network"))).toBeUndefined();
  });
});
