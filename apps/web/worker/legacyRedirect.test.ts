import { describe, expect, it } from "vitest";

import { buildLegacyRedirect } from "./legacyRedirect";
import type { WorkerEnv } from "./workerRuntime";

const LEGACY_HOST = "ai-character-chat-web.pages.dev";
const NEW_ORIGIN = "https://ddona.site";

function createEnv(overrides: Partial<WorkerEnv> = {}): WorkerEnv {
  return {
    ASSETS: { fetch: () => Promise.resolve(new Response()) },
    PUBLIC_ORIGIN: NEW_ORIGIN,
    ...overrides,
  };
}

describe("buildLegacyRedirect", () => {
  it("옛 프로덕션 host의 루트를 새 오리진으로 넘긴다", () => {
    const response = buildLegacyRedirect(new Request(`https://${LEGACY_HOST}/`), createEnv());

    expect(response?.status).toBe(301);
    expect(response?.headers.get("location")).toBe("https://ddona.site/");
  });

  it("경로와 쿼리를 그대로 보존한다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://${LEGACY_HOST}/content/character/abc?sort=latest&x=1`),
      createEnv(),
    );

    expect(response?.headers.get("location")).toBe(
      "https://ddona.site/content/character/abc?sort=latest&x=1",
    );
  });

  // 302 단계에서는 `no-store`가 "되돌릴 수 있다"를 보장했다. 301로 올린 지금은 캐시되는 것이
  // 목적이므로(서치콘솔 주소 변경이 301을 요구한다) 그 헤더가 남아 있으면 안 된다.
  it("301에는 no-store를 붙이지 않는다 — 캐시되는 것이 목적이다", () => {
    const response = buildLegacyRedirect(new Request(`https://${LEGACY_HOST}/`), createEnv());

    expect(response?.headers.get("cache-control")).toBeNull();
  });

  it("HEAD 요청도 넘긴다 — 크롤러가 HEAD를 보낸다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://${LEGACY_HOST}/`, { method: "HEAD" }),
      createEnv(),
    );

    expect(response?.status).toBe(301);
  });

  it("프리뷰 배포는 넘기지 않는다 — 접미사가 같아도 host가 다르다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://a1b2c3d4.${LEGACY_HOST}/`),
      createEnv(),
    );

    expect(response).toBeUndefined();
  });

  it("브랜치 별칭도 넘기지 않는다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://feat-something.${LEGACY_HOST}/`),
      createEnv(),
    );

    expect(response).toBeUndefined();
  });

  it("새 도메인으로 온 요청은 넘기지 않는다", () => {
    const response = buildLegacyRedirect(new Request(`${NEW_ORIGIN}/`), createEnv());

    expect(response).toBeUndefined();
  });

  it("PUBLIC_ORIGIN이 없으면 넘기지 않는다 — 요청 오리진으로 폴백하면 무한 루프다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://${LEGACY_HOST}/`),
      createEnv({ PUBLIC_ORIGIN: undefined }),
    );

    expect(response).toBeUndefined();
  });

  it("PUBLIC_ORIGIN이 아직 옛 도메인이면 넘기지 않는다 — 자기 자신으로 가는 루프다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://${LEGACY_HOST}/`),
      createEnv({ PUBLIC_ORIGIN: `https://${LEGACY_HOST}` }),
    );

    expect(response).toBeUndefined();
  });

  it("PUBLIC_ORIGIN이 URL로 파싱되지 않으면 넘기지 않는다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://${LEGACY_HOST}/`),
      createEnv({ PUBLIC_ORIGIN: "ddona.site" }),
    );

    expect(response).toBeUndefined();
  });

  // scheme 이 빠지면 파싱은 되지만 host 가 빈 값이다 — 여기서 던지면 옛 host 요청이 전부 500 이다.
  it.each(["ddona.site:443", "localhost:8787"])(
    "PUBLIC_ORIGIN이 host 없는 URL(%s)로 파싱되면 던지지 않고 넘기지 않는다",
    (publicOrigin) => {
      const response = buildLegacyRedirect(
        new Request(`https://${LEGACY_HOST}/content/a?q=1`),
        createEnv({ PUBLIC_ORIGIN: publicOrigin }),
      );

      expect(response).toBeUndefined();
    },
  );

  it("PUBLIC_ORIGIN 끝의 슬래시가 이중 슬래시를 만들지 않는다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://${LEGACY_HOST}/content/story/abc`),
      createEnv({ PUBLIC_ORIGIN: "https://ddona.site/" }),
    );

    expect(response?.headers.get("location")).toBe("https://ddona.site/content/story/abc");
  });

  // 경로가 `//` 로 시작하면 `new URL(path, base)` 가 scheme-relative 로 읽어 host 를 바꾼다.
  // `\` 는 URL 파서가 `/` 로 바꾸므로 같은 결과가 된다. 형태를 열거해 막지 않고 목적지 host 만 본다.
  // `//[x` 는 host 자리가 파싱되지 않아 URL 생성자가 던진다 — 던지면 Worker 가 500 을 낸다.
  it.each(["//evil.com/x", "/\\evil.com/x", "///evil.com", "//[x/y"])(
    "경로 %s 가 목적지 host를 바꾸지 못한다 — 새 오리진 안에 머문다",
    (path) => {
      const response = buildLegacyRedirect(
        new Request(`https://${LEGACY_HOST}${path}`),
        createEnv(),
      );

      expect(response?.status).toBe(301);
      expect(new URL(response?.headers.get("location") ?? "").host).toBe("ddona.site");
    },
  );

  it("인코딩된 슬래시는 경로로 남고 host를 바꾸지 않는다", () => {
    const response = buildLegacyRedirect(
      new Request(`https://${LEGACY_HOST}/%2F%2Fevil.com`),
      createEnv(),
    );

    expect(new URL(response?.headers.get("location") ?? "").host).toBe("ddona.site");
  });
});
