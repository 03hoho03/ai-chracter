import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { handleOgImage, parseOgImagePath } from "./ogImage";
import type { CacheLike, WorkerEnv } from "./workerRuntime";
import { fetchUrlOf } from "./testSupport";

const CONTENT_ID = "11111111-2222-4333-8444-555555555555";
const USER_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const THUMBNAIL_URL = "https://r2.example/thumb.webp?X-Amz-Expires=600";

function createCache(): CacheLike & {
  match: ReturnType<typeof vi.fn>;
  put: ReturnType<typeof vi.fn>;
} {
  return {
    match: vi.fn(() => Promise.resolve(undefined)),
    put: vi.fn(() => Promise.resolve()),
  };
}

/** ASSETS는 `/og-default.png`만 알면 된다 — 기본 이미지 폴백의 유일한 출처다. */
function createEnv(overrides: Partial<WorkerEnv> = {}): WorkerEnv & {
  assetFetch: ReturnType<typeof vi.fn>;
} {
  const assetFetch = vi.fn(
    (_request: Request) =>
      new Response("DEFAULT_PNG_BYTES", {
        headers: { "content-type": "image/png" },
      }),
  );
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

/** 콘텐츠 상세 응답에서 이 프록시가 읽는 두 필드만 채운 목. */
function contentDetail(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id: CONTENT_ID,
    name: "테스트 캐릭터",
    thumbnailUrl: THUMBNAIL_URL,
    accessStatus: { kind: "accessible", visibility: "public" },
    ...overrides,
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function imageResponse(): Response {
  return new Response("WEBP_BYTES", {
    headers: { "content-type": "image/webp" },
  });
}

beforeEach(() => {
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("parseOgImagePath", () => {
  it("콘텐츠와 사용자 경로를 판별한다", () => {
    expect(parseOgImagePath(`/og/content/${CONTENT_ID}.jpg`)).toEqual({
      kind: "content",
      id: CONTENT_ID,
    });
    expect(parseOgImagePath(`/og/user/${USER_ID}.jpg`)).toEqual({
      kind: "user",
      id: USER_ID,
    });
  });

  it("UUID가 아닌 id는 받지 않는다", () => {
    expect(parseOgImagePath("/og/content/not-a-uuid.jpg")).toBeUndefined();
    expect(parseOgImagePath("/og/content/12345.jpg")).toBeUndefined();
    expect(parseOgImagePath(`/og/content/${CONTENT_ID}extra.jpg`)).toBeUndefined();
  });

  it("정해진 종류·확장자·깊이가 아니면 받지 않는다", () => {
    expect(parseOgImagePath(`/og/admin/${CONTENT_ID}.jpg`)).toBeUndefined();
    expect(parseOgImagePath(`/og/content/${CONTENT_ID}.png`)).toBeUndefined();
    expect(parseOgImagePath(`/og/content/${CONTENT_ID}`)).toBeUndefined();
    expect(parseOgImagePath(`/og/content/sub/${CONTENT_ID}.jpg`)).toBeUndefined();
    expect(parseOgImagePath("/og-default.png")).toBeUndefined();
  });
});

describe("handleOgImage - 콘텐츠", () => {
  it("썸네일을 스트리밍하고 원본 Content-Type을 따른다", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) =>
      Promise.resolve(
        fetchUrlOf(input).startsWith(THUMBNAIL_URL)
          ? imageResponse()
          : jsonResponse(contentDetail()),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const cache = createCache();

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv(),
      { cache },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("WEBP_BYTES");
    expect(response.headers.get("content-type")).toBe("image/webp");
    expect(response.headers.get("cache-control")).toBe(
      "public, max-age=86400",
    );
    expect(cache.put).toHaveBeenCalledTimes(1);
  });

  it("바깥에 노출되는 주소에 presigned URL이 새지 않는다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) =>
        Promise.resolve(
          fetchUrlOf(input).startsWith(THUMBNAIL_URL)
            ? imageResponse()
            : jsonResponse(contentDetail()),
        ),
      ),
    );

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv(),
      { cache: createCache() },
    );

    // 리다이렉트가 아니라 본문을 흘려보낸다 — 리다이렉트면 만료되는 주소가 크롤러 캐시에 박힌다.
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });

  it("썸네일이 없으면 기본 이미지를 200으로 준다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(jsonResponse(contentDetail({ thumbnailUrl: null }))),
      ),
    );
    const env = createEnv();
    const cache = createCache();

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      env,
      { cache },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("DEFAULT_PNG_BYTES");
    expect(response.headers.get("content-type")).toBe("image/png");
    const [assetRequest] = env.assetFetch.mock.lastCall ?? [];
    expect(new URL(assetRequest.url).pathname).toBe("/og-default.png");
    // 확정된 폴백이라 정상 응답과 같은 수명으로 캐시한다.
    expect(response.headers.get("cache-control")).toBe(
      "public, max-age=86400",
    );
    expect(cache.put).toHaveBeenCalledTimes(1);
  });

  it("없는 콘텐츠는 404다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "Not found" }, 404))),
    );
    const env = createEnv();
    const cache = createCache();

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      env,
      { cache },
    );

    expect(response.status).toBe(404);
    expect(env.assetFetch).not.toHaveBeenCalled();
    expect(cache.put).not.toHaveBeenCalled();
  });

  it.each([
    ["비공개", { kind: "accessible", visibility: "private" }],
    ["운영 제한", { kind: "restricted" }],
    ["삭제됨", { kind: "deleted" }],
  ])("%s 콘텐츠는 200 응답이어도 404다", async (_label, accessStatus) => {
    // `GET /contents/{id}`는 비공개 콘텐츠에도 200 + 썸네일 URL을 준다 — Worker가 걸러야 한다.
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(jsonResponse(contentDetail({ accessStatus }))),
      ),
    );

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv(),
      { cache: createCache() },
    );

    expect(response.status).toBe(404);
  });

  it("링크 공개 콘텐츠는 미리보기를 준다 — 링크 공유가 이 기능의 목적이다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) =>
        Promise.resolve(
          fetchUrlOf(input).startsWith(THUMBNAIL_URL)
            ? imageResponse()
            : jsonResponse(
                contentDetail({
                  accessStatus: { kind: "accessible", visibility: "link" },
                }),
              ),
        ),
      ),
    );

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv(),
      { cache: createCache() },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("WEBP_BYTES");
  });

  it("API가 5xx면 404가 아니라 기본 이미지를 짧은 캐시로 준다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "boom" }, 500))),
    );
    const cache = createCache();

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv(),
      { cache },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("DEFAULT_PNG_BYTES");
    expect(response.headers.get("cache-control")).toBe("public, max-age=60");
    // 몇 초짜리 장애가 하루짜리 기본 이미지로 굳지 않게 캐시에는 넣지 않는다.
    expect(cache.put).not.toHaveBeenCalled();
  });

  it("API 타임아웃·네트워크 오류도 같은 폴백을 탄다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.reject(new DOMException("timed out", "TimeoutError")),
      ),
    );
    const cache = createCache();

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv(),
      { cache },
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("public, max-age=60");
    expect(cache.put).not.toHaveBeenCalled();
  });

  it("원본 이미지를 못 가져오면 기본 이미지로 떨어진다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) =>
        Promise.resolve(
          fetchUrlOf(input).startsWith(THUMBNAIL_URL)
            ? new Response("gone", { status: 403 })
            : jsonResponse(contentDetail()),
        ),
      ),
    );
    const cache = createCache();

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv(),
      { cache },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("DEFAULT_PNG_BYTES");
    expect(response.headers.get("cache-control")).toBe("public, max-age=60");
    expect(cache.put).not.toHaveBeenCalled();
  });
});

describe("handleOgImage - 사용자", () => {
  it("프로필 이미지를 스트리밍한다", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) =>
      Promise.resolve(
        fetchUrlOf(input).startsWith(THUMBNAIL_URL)
          ? imageResponse()
          : jsonResponse({ nickname: "또나", profileImageUrl: THUMBNAIL_URL }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleOgImage(
      get(`/og/user/${USER_ID}.jpg`),
      createEnv(),
      { cache: createCache() },
    );

    // 호출 자체가 없으면 여기서 끊는다 — 예전엔 `String(undefined)`가 `"undefined"`를 만들어
    // "fetch가 안 불렸다"가 "URL이 다르다"로 보고됐다.
    const firstCall = fetchMock.mock.calls[0];
    if (!firstCall) throw new Error("fetch가 호출되지 않았다");

    expect(fetchUrlOf(firstCall[0])).toBe(
      `https://api.example.com/users/${USER_ID}/profile`,
    );
    expect(await response.text()).toBe("WEBP_BYTES");
  });

  it("프로필 이미지가 없으면 기본 이미지를 준다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({ nickname: "또나", profileImageUrl: null }),
        ),
      ),
    );

    const response = await handleOgImage(
      get(`/og/user/${USER_ID}.jpg`),
      createEnv(),
      { cache: createCache() },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("DEFAULT_PNG_BYTES");
  });

  it("삭제된 사용자는 404다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(jsonResponse({ detail: "User not found" }, 404)),
      ),
    );

    const response = await handleOgImage(
      get(`/og/user/${USER_ID}.jpg`),
      createEnv(),
      { cache: createCache() },
    );

    expect(response.status).toBe(404);
  });
});

describe("handleOgImage - 공통", () => {
  it("UUID가 아닌 id는 API를 호출하지 않고 즉시 404다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const cache = createCache();

    const response = await handleOgImage(
      get("/og/content/not-a-uuid.jpg"),
      createEnv(),
      { cache },
    );

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(cache.match).not.toHaveBeenCalled();
  });

  it("캐시에 있으면 API도 원본도 두드리지 않는다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const cache = createCache();
    cache.match.mockResolvedValue(new Response("CACHED"));

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv(),
      { cache },
    );

    expect(await response.text()).toBe("CACHED");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("API_BASE_URL이 없으면 기본 이미지로 버틴다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await handleOgImage(
      get(`/og/content/${CONTENT_ID}.jpg`),
      createEnv({ API_BASE_URL: undefined }),
      { cache: createCache() },
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("DEFAULT_PNG_BYTES");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
