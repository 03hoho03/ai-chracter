import { afterEach, describe, expect, it, vi } from "vitest";

import { handleRequest } from "./handler";
import type { CacheLike, WorkerEnv } from "./workerRuntime";
import { fetchUrlOf } from "./testSupport";

const NOOP_CACHE: CacheLike = {
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
      cache: NOOP_CACHE,
    });

    expect(await response.text()).toBe("/favicon.svg");
  });

  it("/assets/* 는 확장자 유무와 무관하게 ASSETS로 넘긴다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/assets/chunk"), env, {
      cache: NOOP_CACHE,
    });

    expect(await response.text()).toBe("/assets/chunk");
  });

  it("딥링크는 index.html을 200으로 받는다 (SPA 폴백)", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/content/character/42"), env, {
      cache: NOOP_CACHE,
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("/index.html");
  });

  it("루트도 index.html로 서빙한다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/"), env, { cache: NOOP_CACHE });

    expect(await response.text()).toBe("/index.html");
  });

  it("앱에 없는 경로는 셸 본문 그대로 404다 (soft 404 제거)", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/asdf"), env, {
      cache: NOOP_CACHE,
    });

    expect(response.status).toBe(404);
    expect(await response.text()).toBe("/index.html");
  });

  it("정적 자산은 라우트 목록에 없어도 404가 아니다 — 검사 순서가 앞이다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/og-default.png"), env, {
      cache: NOOP_CACHE,
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("/og-default.png");
  });

  it("봇 UA도 없는 경로에서는 API를 부르지 않고 404를 받는다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const env = createEnv();

    const response = await handleRequest(
      new Request("https://ddona.example/asdf", {
        headers: {
          "user-agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
        },
      }),
      env,
      { cache: NOOP_CACHE },
    );

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("/sitemap.xml은 ASSETS로 넘기지 않는다 — 확장자가 있어도 Worker가 만든다", async () => {
    // 라우팅만 확인하면 되므로 API를 두드리지 않는 구성으로 부른다(내용은 sitemap.test.ts).
    const env = createEnv({ API_BASE_URL: undefined });
    vi.spyOn(console, "warn").mockImplementation(() => {});

    const response = await handleRequest(get("/sitemap.xml"), env, {
      cache: NOOP_CACHE,
    });

    expect(env.assetFetch).not.toHaveBeenCalled();
    expect(response.headers.get("content-type")).toBe(
      "application/xml; charset=utf-8",
    );
  });

  it("/robots.txt도 ASSETS로 넘기지 않는다 — Worker가 만든다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/robots.txt"), env, {
      cache: NOOP_CACHE,
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
      fetchUrlOf(input).includes("/contents/")
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
      cache: NOOP_CACHE,
    });

    expect(env.assetFetch).not.toHaveBeenCalled();
    expect(response.headers.get("content-type")).toBe("image/webp");
  });

  it("형식이 틀린 /og/ 경로는 index.html이 아니라 404다", async () => {
    const env = createEnv();

    const response = await handleRequest(get("/og/content/nope.jpg"), env, {
      cache: NOOP_CACHE,
    });

    expect(response.status).toBe(404);
    expect(env.assetFetch).not.toHaveBeenCalled();
  });

  it("봇 UA의 홈은 API 없이 canonical·og:url을 주입한다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // 이 파일의 기본 스텁 셸에는 <head>가 없어 주입 결과가 보이지 않는다(내용은 homeMeta.test.ts).
    const env = createEnv({
      ASSETS: {
        fetch: () =>
          Promise.resolve(
            new Response("<html><head></head><body></body></html>", {
              headers: { "content-type": "text/html; charset=utf-8" },
            }),
          ),
      },
      // API_BASE_URL이 없어도 홈 메타는 나가야 한다 — 조회에 기대지 않는 페이지다.
      API_BASE_URL: undefined,
      PUBLIC_ORIGIN: "https://ddona.example",
    });

    const response = await handleRequest(
      new Request("https://ddona.example/?sort=popular", {
        headers: {
          "user-agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
        },
      }),
      env,
      { cache: NOOP_CACHE },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toContain(
      '<link rel="canonical" href="https://ddona.example/" />',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("일반 브라우저 UA의 홈에는 주입하지 않는다", async () => {
    const env = createEnv();

    const response = await handleRequest(
      new Request("https://ddona.example/", {
        headers: {
          "user-agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        },
      }),
      env,
      { cache: NOOP_CACHE },
    );

    expect(await response.text()).toBe("/index.html");
  });

  it("봇 UA의 콘텐츠 상세는 API를 거쳐 메타를 주입한다", async () => {
    const id = "11111111-2222-4333-8444-555555555555";
    const requestedUrls: string[] = [];
    vi.stubGlobal("fetch", (input: string | URL | Request) => {
      requestedUrls.push(fetchUrlOf(input));
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
      { cache: NOOP_CACHE },
    );

    expect(response.status).toBe(200);
    // 주입 결과 자체는 contentMeta.test.ts가 본다(이 스텁의 셸에는 <head>가 없다).
    expect(requestedUrls).toEqual([`https://api.example.com/contents/${id}`]);
  });

  it("봇 UA의 프로필은 프로필 API를 거쳐 메타를 주입한다", async () => {
    const id = "11111111-2222-4333-8444-555555555555";
    const requestedUrls: string[] = [];
    vi.stubGlobal("fetch", (input: string | URL | Request) => {
      requestedUrls.push(fetchUrlOf(input));
      return Promise.resolve(
        new Response(JSON.stringify({ nickname: "달빛작가", bio: null }), {
          headers: { "content-type": "application/json" },
        }),
      );
    });
    const env = createEnv();

    const response = await handleRequest(
      new Request(`https://ddona.example/profile/${id}`, {
        headers: { "user-agent": "facebookexternalhit/1.1" },
      }),
      env,
      { cache: NOOP_CACHE },
    );

    expect(response.status).toBe(200);
    expect(requestedUrls).toEqual([
      `https://api.example.com/users/${id}/profile`,
    ]);
  });

  it("일반 브라우저 UA는 프로필에서도 API를 부르지 않는다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const env = createEnv();

    const response = await handleRequest(
      new Request(
        "https://ddona.example/profile/11111111-2222-4333-8444-555555555555",
        {
          headers: {
            "user-agent":
              "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
          },
        },
      ),
      env,
      { cache: NOOP_CACHE },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("/index.html");
    expect(fetchMock).not.toHaveBeenCalled();
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
      { cache: NOOP_CACHE },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("/index.html");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("잘못된 형식의 콘텐츠 id에서 봇은 404, 같은 URL의 일반 UA는 200이다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const env = createEnv();
    const path = "/content/character/not-a-uuid";

    const botResponse = await handleRequest(
      new Request(`https://ddona.example${path}`, {
        headers: { "user-agent": "Googlebot/2.1" },
      }),
      env,
      { cache: NOOP_CACHE },
    );
    const userResponse = await handleRequest(
      new Request(`https://ddona.example${path}`, {
        headers: {
          "user-agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        },
      }),
      env,
      { cache: NOOP_CACHE },
    );

    expect(botResponse.status).toBe(404);
    expect(userResponse.status).toBe(200);
    // id 형식이 틀리면 봇 쪽도 API를 두드리지 않는다 — 크롤러가 곧 API 부하가 된다.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("없는 사용자에서 봇은 404, 같은 URL의 일반 UA는 왕복 없이 200이다", async () => {
    const id = "11111111-2222-4333-8444-555555555555";
    const requestedUrls: string[] = [];
    vi.stubGlobal("fetch", (input: string | URL | Request) => {
      requestedUrls.push(fetchUrlOf(input));
      return Promise.resolve(
        new Response(JSON.stringify({ detail: "Not Found" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
      );
    });
    const env = createEnv();

    const botResponse = await handleRequest(
      new Request(`https://ddona.example/profile/${id}`, {
        headers: { "user-agent": "Yeti/1.1 (NHN Corp.)" },
      }),
      env,
      { cache: NOOP_CACHE },
    );
    const userResponse = await handleRequest(
      new Request(`https://ddona.example/profile/${id}`, {
        headers: {
          "user-agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        },
      }),
      env,
      { cache: NOOP_CACHE },
    );

    expect(botResponse.status).toBe(404);
    expect(userResponse.status).toBe(200);
    // 왕복은 봇 요청 하나뿐이다 — 사용자 요청은 검사 자체를 하지 않는다.
    expect(requestedUrls).toEqual([
      `https://api.example.com/users/${id}/profile`,
    ]);
  });

  it("요청 host가 PUBLIC_ORIGIN과 다르면 SPA 셸에 noindex가 붙는다", async () => {
    const env = createEnv({ PUBLIC_ORIGIN: "https://ddona.production" });

    const response = await handleRequest(get("/content/character/42"), env, {
      cache: NOOP_CACHE,
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
      cache: NOOP_CACHE,
    });

    expect(response.headers.get("x-robots-tag")).toBe("noindex");
  });

  it("정식 host의 응답에는 noindex가 붙지 않는다", async () => {
    const env = createEnv({ PUBLIC_ORIGIN: "https://ddona.example" });

    const response = await handleRequest(get("/content/character/42"), env, {
      cache: NOOP_CACHE,
    });

    expect(response.headers.get("x-robots-tag")).toBeNull();
  });

  it("API_BASE_URL이 없어도 정적 자산과 SPA 셸은 정상 서빙한다", async () => {
    const env = createEnv({ API_BASE_URL: undefined });

    const shell = await handleRequest(get("/login"), env, {
      cache: NOOP_CACHE,
    });
    const asset = await handleRequest(get("/assets/app.js"), env, {
      cache: NOOP_CACHE,
    });

    expect(shell.status).toBe(200);
    expect(await shell.text()).toBe("/index.html");
    expect(await asset.text()).toBe("/assets/app.js");
  });

  // 배선 위치 검사다. 판별 규칙 자체는 legacyRedirect.test.ts가 본다.
  describe("옛 도메인 리다이렉트", () => {
    const LEGACY = "https://ai-character-chat-web.pages.dev";

    function legacyEnv() {
      return createEnv({ PUBLIC_ORIGIN: "https://ddona.example" });
    }

    it("정적 자산도 넘긴다 — 자산 검사보다 앞에 있어야 한다", async () => {
      const env = legacyEnv();

      const response = await handleRequest(new Request(`${LEGACY}/assets/app.js`), env, {
        cache: NOOP_CACHE,
      });

      expect(response.status).toBe(302);
      expect(response.headers.get("location")).toBe("https://ddona.example/assets/app.js");
      expect(env.assetFetch).not.toHaveBeenCalled();
    });

    it("Worker가 만드는 경로(/sitemap.xml)도 넘긴다", async () => {
      const response = await handleRequest(new Request(`${LEGACY}/sitemap.xml`), legacyEnv(), {
        cache: NOOP_CACHE,
      });

      expect(response.status).toBe(302);
      expect(response.headers.get("location")).toBe("https://ddona.example/sitemap.xml");
    });

    it("앱에 없는 경로도 404가 아니라 리다이렉트다", async () => {
      const response = await handleRequest(new Request(`${LEGACY}/없는경로`), legacyEnv(), {
        cache: NOOP_CACHE,
      });

      expect(response.status).toBe(302);
    });

    it("프리뷰 배포는 평소대로 서빙한다", async () => {
      const response = await handleRequest(
        new Request(`https://a1b2c3d4.ai-character-chat-web.pages.dev/login`),
        legacyEnv(),
        { cache: NOOP_CACHE },
      );

      expect(response.status).toBe(200);
      expect(await response.text()).toBe("/index.html");
    });
  });
});
