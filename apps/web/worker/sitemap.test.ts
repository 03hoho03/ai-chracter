import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildSitemapXml, handleSitemap } from "./sitemap";
import type { CacheLike, WorkerEnv } from "./workerRuntime";

const NOOP_CACHE: CacheLike = {
  match: () => Promise.resolve(undefined),
  put: () => Promise.resolve(),
};

function createEnv(overrides: Partial<WorkerEnv> = {}): WorkerEnv {
  return {
    ASSETS: { fetch: () => Promise.resolve(new Response("asset")) },
    API_BASE_URL: "https://api.example.com",
    PUBLIC_ORIGIN: "https://ddona.example",
    ...overrides,
  };
}

const SITEMAP_REQUEST = new Request("https://preview.pages.dev/sitemap.xml");

/**
 * `/contents`를 흉내 내는 fetch 목. 타입별로 "페이지 배열"을 주면 커서를 페이지 인덱스로 쓴다.
 * 실제 커서는 base64 문자열이지만 Worker는 값을 해석하지 않고 되돌려 보내기만 한다.
 */
function stubContentsApi(pagesByType: Record<string, string[][]>) {
  const fetchMock = vi.fn((input: string) => {
    const url = new URL(input);
    const type = url.searchParams.get("type") ?? "";
    const cursor = Number(url.searchParams.get("cursor") ?? "0");
    const pages = pagesByType[type] ?? [];
    const items = (pages[cursor] ?? []).map((id) => ({
      id,
      name: "이름",
      type,
    }));
    const nextCursor = cursor + 1 < pages.length ? String(cursor + 1) : null;

    return Promise.resolve(
      new Response(JSON.stringify({ items, nextCursor }), {
        headers: { "content-type": "application/json" },
      }),
    );
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("buildSitemapXml", () => {
  it("sitemap 0.9 urlset을 만든다", () => {
    const xml = buildSitemapXml([
      "https://ddona.example/",
      "https://ddona.example/content/character/1",
    ]);

    expect(xml).toBe(
      '<?xml version="1.0" encoding="UTF-8"?>\n' +
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
        "  <url><loc>https://ddona.example/</loc></url>\n" +
        "  <url><loc>https://ddona.example/content/character/1</loc></url>\n" +
        "</urlset>\n",
    );
  });

  it("lastmod를 넣지 않는다 — 목록 API에 갱신 시각이 없다", () => {
    expect(buildSitemapXml(["https://ddona.example/"])).not.toContain(
      "lastmod",
    );
  });

  it("URL을 이스케이프한다 — 앰퍼샌드 하나로 XML 전체가 깨진다", () => {
    expect(buildSitemapXml(["https://ddona.example/?a=1&b=2"])).toContain(
      "<loc>https://ddona.example/?a=1&amp;b=2</loc>",
    );
  });

  it("목록이 비어도 유효한 urlset이다", () => {
    const xml = buildSitemapXml([]);

    expect(xml).toContain("<urlset");
    expect(xml).toContain("</urlset>");
    expect(xml).not.toContain("<url>");
  });
});

describe("handleSitemap", () => {
  it("홈 + 타입별 공개 콘텐츠 전건을 커서로 순회해 담는다", async () => {
    const fetchMock = stubContentsApi({
      character: [["c1", "c2"], ["c3"]],
      story: [["s1"]],
    });

    const response = await handleSitemap(SITEMAP_REQUEST, createEnv(), {
      cache: NOOP_CACHE,
    });
    const xml = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(
      "application/xml; charset=utf-8",
    );
    expect(response.headers.get("cache-control")).toBe(
      "public, max-age=3600",
    );
    expect(xml.match(/<loc>/g)).toHaveLength(5);
    expect(xml).toContain("<loc>https://ddona.example/</loc>");
    expect(xml).toContain(
      "<loc>https://ddona.example/content/character/c3</loc>",
    );
    expect(xml).toContain("<loc>https://ddona.example/content/story/s1</loc>");
    // 첫 페이지엔 커서가 없고, 다음 페이지부터 서버가 준 커서를 그대로 붙인다.
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "https://api.example.com/contents?type=character",
      "https://api.example.com/contents?type=character&cursor=1",
      "https://api.example.com/contents?type=story",
    ]);
  });

  it("URL은 요청 host가 아니라 PUBLIC_ORIGIN을 쓴다 — 프리뷰가 색인돼도 프로덕션을 가리킨다", async () => {
    stubContentsApi({ character: [["c1"]], story: [] });

    const response = await handleSitemap(SITEMAP_REQUEST, createEnv(), {
      cache: NOOP_CACHE,
    });

    expect(await response.text()).not.toContain("preview.pages.dev");
  });

  it("타입당 50페이지에서 자르고 경고를 남긴다", async () => {
    const manyPages = Array.from({ length: 60 }, (_, page) => [`c${page}`]);
    stubContentsApi({ character: manyPages, story: [] });

    const response = await handleSitemap(SITEMAP_REQUEST, createEnv(), {
      cache: NOOP_CACHE,
    });
    const xml = await response.text();

    // 홈 1 + 캐릭터 50페이지 × 1건.
    expect(xml.match(/<loc>/g)).toHaveLength(51);
    expect(xml).toContain("/content/character/c49");
    expect(xml).not.toContain("/content/character/c50");
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("type=character"),
    );
  });

  it("API가 5xx면 홈만 담은 최소 sitemap을 200으로 준다", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve(new Response("boom", { status: 503 })),
    );

    const response = await handleSitemap(SITEMAP_REQUEST, createEnv(), {
      cache: NOOP_CACHE,
    });
    const xml = await response.text();

    expect(response.status).toBe(200);
    expect(xml.match(/<loc>/g)).toHaveLength(1);
    expect(xml).toContain("<loc>https://ddona.example/</loc>");
    expect(console.warn).toHaveBeenCalled();
  });

  it("fetch 자체가 실패해도 최소 sitemap을 200으로 준다", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("network down")));

    const response = await handleSitemap(SITEMAP_REQUEST, createEnv(), {
      cache: NOOP_CACHE,
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toContain("<loc>https://ddona.example/</loc>");
  });

  it("두 번째 페이지에서 실패하면 부분 목록을 내보내지 않는다", async () => {
    const fetchMock = vi.fn((input: string) =>
      Promise.resolve(
        input.includes("cursor=")
          ? new Response("boom", { status: 500 })
          : new Response(
              JSON.stringify({ items: [{ id: "c1" }], nextCursor: "1" }),
            ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleSitemap(SITEMAP_REQUEST, createEnv(), {
      cache: NOOP_CACHE,
    });

    expect(await response.text()).not.toContain("c1");
  });

  it("API_BASE_URL이 없으면 API를 부르지 않고 최소 sitemap을 준다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleSitemap(
      SITEMAP_REQUEST,
      createEnv({ API_BASE_URL: undefined }),
      { cache: NOOP_CACHE },
    );

    expect(response.status).toBe(200);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("캐시에 있으면 API를 부르지 않고 캐시된 응답을 준다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const cache: CacheLike = {
      match: () => Promise.resolve(new Response("<urlset>cached</urlset>")),
      put: () => Promise.resolve(),
    };

    const response = await handleSitemap(SITEMAP_REQUEST, createEnv(), {
      cache,
    });

    expect(await response.text()).toBe("<urlset>cached</urlset>");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("성공 응답은 캐시에 넣고, 실패 폴백은 넣지 않는다", async () => {
    const put = vi.fn(() => Promise.resolve());
    const cache: CacheLike = { match: () => Promise.resolve(undefined), put };

    stubContentsApi({ character: [["c1"]], story: [] });
    const ok = await handleSitemap(SITEMAP_REQUEST, createEnv(), { cache });

    expect(put).toHaveBeenCalledTimes(1);
    // 캐시에 넣은 뒤에도 반환한 응답의 본문은 읽을 수 있어야 한다(clone).
    expect(await ok.text()).toContain("<loc>");

    vi.stubGlobal("fetch", () => Promise.reject(new Error("network down")));
    const fallback = await handleSitemap(SITEMAP_REQUEST, createEnv(), {
      cache,
    });

    expect(put).toHaveBeenCalledTimes(1);
    expect(fallback.headers.get("cache-control")).toBe("public, max-age=60");
  });
});
