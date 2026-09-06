import { describe, expect, it } from "vitest";

import { buildLegalHead, handleLegalMeta, parseLegalPath } from "./legalMeta";
import type { WorkerEnv } from "./workerRuntime";

const SHELL_HTML = `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <title>또나 — AI 캐릭터 챗</title>
    <meta name="description" content="AI 캐릭터 챗 또나" />
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

function botRequest(path: string): Request {
  return new Request(`https://ddona.local${path}`, {
    headers: { "user-agent": "Googlebot/2.1 (+http://www.google.com/bot.html)" },
  });
}

describe("parseLegalPath", () => {
  it("/terms·/privacy만 알아본다", () => {
    expect(parseLegalPath("/terms")).toBe("terms");
    expect(parseLegalPath("/privacy")).toBe("privacy");
  });

  it("그 밖의 경로는 undefined", () => {
    expect(parseLegalPath("/")).toBeUndefined();
    expect(parseLegalPath("/terms/")).toBeUndefined();
    expect(parseLegalPath("/legal/terms")).toBeUndefined();
  });
});

describe("buildLegalHead", () => {
  it("종류별 title·description과 정식 오리진 기준 canonical을 만든다", () => {
    const head = buildLegalHead("terms", "https://ddona.example");

    expect(head).toContain("<title>이용약관 — 또나</title>");
    expect(head).toContain(
      '<link rel="canonical" href="https://ddona.example/terms" />',
    );
  });
});

describe("handleLegalMeta", () => {
  it("셸에 title·description·canonical을 주입해 200으로 돌려준다", async () => {
    const response = await handleLegalMeta(
      botRequest("/privacy"),
      createEnv(),
      "privacy",
    );
    const html = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(
      "text/html; charset=utf-8",
    );
    expect(html).toContain("<title>개인정보처리방침 — 또나</title>");
    expect(html).toContain(
      '<link rel="canonical" href="https://ddona.example/privacy" />',
    );
  });

  it("PUBLIC_ORIGIN이 없으면 요청 오리진으로 폴백한다 (로컬 개발)", async () => {
    const response = await handleLegalMeta(
      botRequest("/terms"),
      createEnv({ PUBLIC_ORIGIN: undefined }),
      "terms",
    );
    const html = await response.text();

    expect(html).toContain(
      '<link rel="canonical" href="https://ddona.local/terms" />',
    );
  });
});
