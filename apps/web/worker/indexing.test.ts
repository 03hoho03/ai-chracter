import { describe, expect, it } from "vitest";

import { applyIndexingPolicy, isPreviewHost } from "./indexing";
import type { WorkerEnv } from "./types";

const ASSETS = { fetch: () => Promise.resolve(new Response("asset")) };

function env(publicOrigin?: string): WorkerEnv {
  return publicOrigin === undefined
    ? { ASSETS }
    : { ASSETS, PUBLIC_ORIGIN: publicOrigin };
}

function html(): Response {
  return new Response("<html></html>", {
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}

describe("isPreviewHost", () => {
  it("요청 host가 PUBLIC_ORIGIN의 host와 같으면 false", () => {
    expect(
      isPreviewHost(
        env("https://ddona.example"),
        new Request("https://ddona.example/content/character/1"),
      ),
    ).toBe(false);
  });

  it("요청 host가 다르면 true — 프리뷰 배포와 로컬이 여기에 걸린다", () => {
    expect(
      isPreviewHost(env("https://ddona.example"), new Request("https://abc123.pages.dev/")),
    ).toBe(true);
    expect(
      isPreviewHost(env("https://ddona.example"), new Request("http://localhost:8788/")),
    ).toBe(true);
  });

  it("스킴이 달라도 host가 같으면 false — 판단 기준은 host 하나다", () => {
    expect(
      isPreviewHost(env("https://ddona.example"), new Request("http://ddona.example/")),
    ).toBe(false);
  });

  it("PUBLIC_ORIGIN이 없으면 false — 환경변수 실수로 프로덕션을 noindex 하지 않는다", () => {
    expect(isPreviewHost(env(), new Request("https://ddona.example/"))).toBe(false);
  });

  it("PUBLIC_ORIGIN이 URL이 아니면 false — 오타가 사이트 전체를 색인에서 빼면 안 된다", () => {
    expect(isPreviewHost(env("ddona.example"), new Request("https://ddona.example/"))).toBe(
      false,
    );
  });
});

describe("applyIndexingPolicy", () => {
  it("정식 host의 HTML에는 헤더를 붙이지 않는다", () => {
    const response = applyIndexingPolicy(
      html(),
      env("https://ddona.example"),
      new Request("https://ddona.example/"),
    );

    expect(response.headers.get("x-robots-tag")).toBeNull();
  });

  it("프리뷰 host의 HTML에는 X-Robots-Tag: noindex를 붙인다", async () => {
    const response = applyIndexingPolicy(
      html(),
      env("https://ddona.example"),
      new Request("https://abc123.pages.dev/"),
    );

    expect(response.headers.get("x-robots-tag")).toBe("noindex");
    expect(await response.text()).toBe("<html></html>");
  });

  it("프리뷰 host의 XML(sitemap)에도 붙인다", () => {
    const sitemap = new Response("<urlset />", {
      headers: { "content-type": "application/xml; charset=utf-8" },
    });

    const response = applyIndexingPolicy(
      sitemap,
      env("https://ddona.example"),
      new Request("https://abc123.pages.dev/sitemap.xml"),
    );

    expect(response.headers.get("x-robots-tag")).toBe("noindex");
  });

  it("HTML·XML이 아닌 응답은 그대로 통과시킨다", () => {
    const script = new Response("export {}", {
      headers: { "content-type": "application/javascript" },
    });

    const response = applyIndexingPolicy(
      script,
      env("https://ddona.example"),
      new Request("https://abc123.pages.dev/assets/app.js"),
    );

    expect(response).toBe(script);
    expect(response.headers.get("x-robots-tag")).toBeNull();
  });

  it("상태 코드와 나머지 헤더를 보존한다", () => {
    const notFound = new Response("<html>404</html>", {
      status: 404,
      headers: { "content-type": "text/html", "cache-control": "no-store" },
    });

    const response = applyIndexingPolicy(
      notFound,
      env("https://ddona.example"),
      new Request("https://abc123.pages.dev/asdf"),
    );

    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("x-robots-tag")).toBe("noindex");
  });
});
