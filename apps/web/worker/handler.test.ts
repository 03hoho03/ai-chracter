import { afterEach, describe, expect, it, vi } from "vitest";

import { handleRequest } from "./handler";
import type { CacheLike, WorkerEnv } from "./types";

const noopCache: CacheLike = {
  match: () => Promise.resolve(undefined),
  put: () => Promise.resolve(),
};

/** ASSETS는 실제 자산 목록 대신 "요청받은 경로"를 본문으로 되돌려주는 스텁으로 둔다. */
function createEnv(overrides: Partial<WorkerEnv> = {}): WorkerEnv & {
  assetFetch: ReturnType<typeof vi.fn>;
} {
  const assetFetch = vi.fn((request: Request) => {
    const { pathname } = new URL(request.url);
    return new Response(pathname, {
      status: 200,
      // 응답 정책(X-Robots-Tag)이 content-type으로 갈리므로 스텁도 타입을 준다.
      headers: {
        "content-type": pathname.endsWith(".html")
          ? "text/html; charset=utf-8"
          : "application/octet-stream",
      },
    });
  });
  return {
    ASSETS: { fetch: (request) => Promise.resolve(assetFetch(request)) },
    API_BASE_URL: "https://api.example.com",
    assetFetch,
    ...overrides,
  };
}

function get(path: string): Request {
  return new Request(`https://ddona.example${path}`);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("handleRequest", () => {
  it("확장자가 있는 경로는 요청을 그대로 ASSETS로 넘긴다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/favicon.svg"), env, {
      cache: noopCache,
    });

    expect(await response.text()).toBe("/favicon.svg");
  });

  it("/assets/* 는 확장자 유무와 무관하게 ASSETS로 넘긴다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/assets/chunk"), env, {
      cache: noopCache,
    });

    expect(await response.text()).toBe("/assets/chunk");
  });

  it("딥링크는 index.html을 200으로 받는다 (SPA 폴백)", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/content/character/42"), env, {
      cache: noopCache,
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("/index.html");
  });

  it("루트도 index.html로 서빙한다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/"), env, { cache: noopCache });

    expect(await response.text()).toBe("/index.html");
  });

  it("/sitemap.xml은 ASSETS로 넘기지 않는다 — 확장자가 있어도 Worker가 만든다", async () => {
    // 라우팅만 확인하면 되므로 API를 두드리지 않는 구성으로 부른다(내용은 sitemap.test.ts).
    const env = createEnv({ API_BASE_URL: undefined });
    vi.spyOn(console, "warn").mockImplementation(() => {});

    const response = await handleRequest(get("/sitemap.xml"), env, {
      cache: noopCache,
    });

    expect(env.assetFetch).not.toHaveBeenCalled();
    expect(response.headers.get("content-type")).toBe(
      "application/xml; charset=utf-8",
    );
  });

  it("/robots.txt도 ASSETS로 넘기지 않는다 — Worker가 만든다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/robots.txt"), env, {
      cache: noopCache,
    });

    expect(env.assetFetch).not.toHaveBeenCalled();
    expect(response.headers.get("content-type")).toBe(
      "text/plain; charset=utf-8",
    );
  });

  it("/og/content/{id}.jpg는 ASSETS로 넘기지 않는다 — Worker가 API를 거쳐 만든다", async () => {
    const id = "11111111-2222-4333-8444-555555555555";
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response("IMAGE", { headers: { "content-type": "image/webp" } }),
      ),
    );
    vi.stubGlobal("fetch", (input: string | URL | Request) =>
      String(input).includes("/contents/")
        ? Promise.resolve(
            new Response(
              JSON.stringify({
                thumbnailUrl: "https://r2.example/thumb.webp",
                accessStatus: { kind: "accessible", visibility: "public" },
              }),
              { headers: { "content-type": "application/json" } },
            ),
          )
        : fetchMock(),
    );
    const env = createEnv();

    const response = await handleRequest(get(`/og/content/${id}.jpg`), env, {
      cache: noopCache,
    });

    expect(env.assetFetch).not.toHaveBeenCalled();
    expect(response.headers.get("content-type")).toBe("image/webp");
  });

  it("형식이 틀린 /og/ 경로는 index.html이 아니라 404다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/og/content/nope.jpg"), env, {
      cache: noopCache,
    });

    expect(response.status).toBe(404);
    expect(env.assetFetch).not.toHaveBeenCalled();
  });

  it("봇 UA의 콘텐츠 상세는 API를 거쳐 메타를 주입한다", async () => {
    const id = "11111111-2222-4333-8444-555555555555";
    const requestedUrls: string[] = [];
    vi.stubGlobal("fetch", (input: string | URL | Request) => {
      requestedUrls.push(String(input));
      return Promise.resolve(
        new Response(
          JSON.stringify({
            type: "character",
            name: "루나",
            oneLiner: "달빛 마녀",
            accessStatus: { kind: "accessible", visibility: "public" },
          }),
          { headers: { "content-type": "application/json" } },
        ),
      );
    });
    const env = createEnv();

    const response = await handleRequest(
      new Request(`https://ddona.example/content/character/${id}`, {
        headers: {
          "user-agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
        },
      }),
      env,
      { cache: noopCache },
    );

    expect(response.status).toBe(200);
    // 주입 결과 자체는 content-meta.test.ts가 본다(이 스텁의 셸에는 <head>가 없다).
    expect(requestedUrls).toEqual([`https://api.example.com/contents/${id}`]);
  });

  it("일반 브라우저 UA는 같은 URL에서 API를 부르지 않는다", async () => {
    const id = "11111111-2222-4333-8444-555555555555";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const env = createEnv();

    const response = await handleRequest(
      new Request(`https://ddona.example/content/character/${id}`, {
        headers: {
          "user-agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        },
      }),
      env,
      { cache: noopCache },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("/index.html");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("요청 host가 PUBLIC_ORIGIN과 다르면 SPA 셸에 noindex가 붙는다", async () => {
    const env = createEnv({ PUBLIC_ORIGIN: "https://ddona.production" });

    const response = await handleRequest(get("/content/character/42"), env, {
      cache: noopCache,
    });

    expect(response.headers.get("x-robots-tag")).toBe("noindex");
  });

  it("noindex는 sitemap 응답에도 소급 적용된다 — 라우트별로 기억하지 않는다", async () => {
    const env = createEnv({
      API_BASE_URL: undefined,
      PUBLIC_ORIGIN: "https://ddona.production",
    });
    vi.spyOn(console, "warn").mockImplementation(() => {});

    const response = await handleRequest(get("/sitemap.xml"), env, {
      cache: noopCache,
    });

    expect(response.headers.get("x-robots-tag")).toBe("noindex");
  });

  it("정식 host의 응답에는 noindex가 붙지 않는다", async () => {
    const env = createEnv({ PUBLIC_ORIGIN: "https://ddona.example" });

    const response = await handleRequest(get("/content/character/42"), env, {
      cache: noopCache,
    });

    expect(response.headers.get("x-robots-tag")).toBeNull();
  });

  it("API_BASE_URL이 없어도 정적 자산과 SPA 셸은 정상 서빙한다", async () => {
    const env = createEnv({ API_BASE_URL: undefined });

    const shell = await handleRequest(get("/login"), env, {
      cache: noopCache,
    });
    const asset = await handleRequest(get("/assets/app.js"), env, {
      cache: noopCache,
    });

    expect(shell.status).toBe(200);
    expect(await shell.text()).toBe("/index.html");
    expect(await asset.text()).toBe("/assets/app.js");
  });
});
