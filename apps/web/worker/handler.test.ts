import { describe, expect, it, vi } from "vitest";

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
  const assetFetch = vi.fn(
    (request: Request) =>
      new Response(new URL(request.url).pathname, { status: 200 }),
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
