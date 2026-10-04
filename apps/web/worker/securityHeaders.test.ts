import { describe, expect, it } from "vitest";

import { applySecurityHeaders } from "./securityHeaders";

describe("applySecurityHeaders", () => {
  it("헤더가 없는 응답에 기본 보안 헤더 네 개를 붙인다", () => {
    const response = applySecurityHeaders(new Response("body"));

    expect(response.headers.get("strict-transport-security")).toBe("max-age=31536000");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("x-frame-options")).toBe("DENY");
    expect(response.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
  });

  // `/_ingest/*` 로 나가는 Bugsink 응답은 자기 값(더 엄격한 `same-origin`)을 이미 준다.
  it("이미 있는 값은 덮어쓰지 않는다", () => {
    const response = applySecurityHeaders(
      new Response("body", {
        headers: { "referrer-policy": "same-origin", "x-frame-options": "SAMEORIGIN" },
      }),
    );

    expect(response.headers.get("referrer-policy")).toBe("same-origin");
    expect(response.headers.get("x-frame-options")).toBe("SAMEORIGIN");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  });

  // ASSETS·업스트림 fetch·Response.redirect 가 돌려주는 응답은 헤더가 불변이다. 그대로 고치면
  // 운영에서만 TypeError 로 500 이 나고, 가변 헤더 스텁만 쓰는 테스트는 그걸 못 잡는다.
  it("헤더가 불변인 응답도 감싸서 헤더를 붙이고 상태·location을 보존한다", async () => {
    const immutable = Response.redirect("https://ddona.example/next", 301);
    expect(() => immutable.headers.set("x-probe", "1")).toThrow(TypeError);

    const response = applySecurityHeaders(immutable);

    expect(response.status).toBe(301);
    expect(response.headers.get("location")).toBe("https://ddona.example/next");
    expect(response.headers.get("x-frame-options")).toBe("DENY");
    expect(await response.text()).toBe("");
  });

  it("본문을 그대로 넘긴다", async () => {
    const response = applySecurityHeaders(new Response("hello", { status: 404 }));

    expect(response.status).toBe(404);
    expect(await response.text()).toBe("hello");
  });
});
