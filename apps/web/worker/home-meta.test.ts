import { describe, expect, it } from "vitest";

import { buildHomeHead, handleHomeMeta } from "./home-meta";
import type { WorkerEnv } from "./types";

/** index.html과 같은 모양 — 홈 기본 메타는 이미 박혀 있고 Worker는 두 개만 더한다. */
const SHELL_HTML = `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <title>또나 — AI 캐릭터 챗</title>
    <meta name="description" content="AI 캐릭터 챗 또나" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <meta property="og:title" content="또나 — AI 캐릭터 챗" />
    <meta property="og:image" content="https://ddona.example/og-default.png" />
    <meta property="og:type" content="website" />
  </head>
  <body><div id="root"></div></body>
</html>
`;

function createEnv(overrides: Partial<WorkerEnv> = {}): WorkerEnv {
  return {
    ASSETS: {
      fetch: () =>
        Promise.resolve(
          new Response(SHELL_HTML, {
            headers: { "content-type": "text/html; charset=utf-8" },
          }),
        ),
    },
    API_BASE_URL: "https://api.example.com",
    PUBLIC_ORIGIN: "https://ddona.example",
    ...overrides,
  };
}

function botRequest(path = "/"): Request {
  return new Request(`https://ddona.local${path}`, {
    headers: { "user-agent": "Googlebot/2.1 (+http://www.google.com/bot.html)" },
  });
}

describe("buildHomeHead", () => {
  it("canonical과 og:url을 정식 오리진 기준으로 만든다", () => {
    const head = buildHomeHead("https://ddona.example");

    expect(head).toContain(
      '<link rel="canonical" href="https://ddona.example/" />',
    );
    expect(head).toContain(
      '<meta property="og:url" content="https://ddona.example/" />',
    );
  });

  it("index.html에 이미 있는 title·og는 만들지 않는다 — 두 태그뿐이다", () => {
    const head = buildHomeHead("https://ddona.example");

    expect(head.split("\n")).toHaveLength(2);
    expect(head).not.toContain("<title>");
    expect(head).not.toContain("og:title");
  });
});

describe("handleHomeMeta", () => {
  it("셸에 canonical·og:url을 주입해 200으로 돌려준다", async () => {
    const response = await handleHomeMeta(botRequest(), createEnv());
    const html = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(
      "text/html; charset=utf-8",
    );
    expect(html).toContain(
      '<link rel="canonical" href="https://ddona.example/" />',
    );
    expect(html).toContain(
      '<meta property="og:url" content="https://ddona.example/" />',
    );
  });

  it("index.html의 홈 기본 메타는 그대로 남는다 — 키가 겹치지 않는다", async () => {
    const response = await handleHomeMeta(botRequest(), createEnv());
    const html = await response.text();

    expect(html).toContain("<title>또나 — AI 캐릭터 챗</title>");
    expect(html).toContain(
      '<meta property="og:title" content="또나 — AI 캐릭터 챗" />',
    );
    expect(html).toContain(
      '<meta property="og:image" content="https://ddona.example/og-default.png" />',
    );
    expect(html).toContain('<link rel="icon" href="/favicon.svg"');
  });

  it("정렬·장르 쿼리가 붙어도 canonical은 쿼리 없는 홈 하나다", async () => {
    const response = await handleHomeMeta(
      botRequest("/?sort=genre&genre=11111111-2222-4333-8444-555555555555"),
      createEnv(),
    );
    const html = await response.text();

    expect(html).toContain(
      '<link rel="canonical" href="https://ddona.example/" />',
    );
    expect(html).not.toContain("sort=genre");
  });

  it("PUBLIC_ORIGIN이 없으면 요청 오리진으로 폴백한다 (로컬 개발)", async () => {
    const response = await handleHomeMeta(
      botRequest(),
      createEnv({ PUBLIC_ORIGIN: undefined }),
    );
    const html = await response.text();

    expect(html).toContain(
      '<link rel="canonical" href="https://ddona.local/" />',
    );
  });
});
