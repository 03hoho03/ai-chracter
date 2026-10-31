import { describe, expect, it } from "vitest";

import { buildAboutBody, buildAboutHead, handleAboutMeta } from "./aboutMeta";
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

describe("buildAboutHead", () => {
  it("title·description과 정식 오리진 기준 canonical을 만든다", () => {
    const head = buildAboutHead("https://ddona.example");

    expect(head).toContain("<title>서비스 소개 — 또나</title>");
    expect(head).toContain(
      '<meta name="description" content="또나는 AI 캐릭터와 대화하고, 직접 만든 캐릭터와 스토리를 다른 사람과 나누는 서비스예요." />',
    );
    expect(head).toContain(
      '<link rel="canonical" href="https://ddona.example/about" />',
    );
  });
});

describe("buildAboutBody", () => {
  it("소개 페이지의 기능 문장이 페이지 소스에 그대로 남아 있다 — 사본이 어긋나면 여기서 깨진다", () => {
    const pageSource = Object.values(
      import.meta.glob<string>("../src/pages/about/ui/AboutPage.tsx", {
        query: "?raw",
        import: "default",
        eager: true,
      }),
    ).join("");
    const sentences = [...buildAboutBody().matchAll(/<(?:h2|p)>([^<]+)<\/(?:h2|p)>/g)]
      .map(([, text]) => text)
      // `${SITE_NAME}`를 끼운 문장은 JSX에서 줄바꿈·중괄호로 쪼개져 있어 그대로 찾을 수 없다.
      .filter((text): text is string => text !== undefined && !text.includes("또나"));

    expect(sentences.length).toBeGreaterThan(10);
    for (const sentence of sentences) expect(pageSource).toContain(sentence);
  });

  // 하루 무료 대화는 없고 출석판은 늘 열려 있다 — 소개 문장도 출석 보상을 말하고 "무료 사용량 밖" 을 말하지 않는다.
  // 페이지 쪽도 함께 보는 이유: 봇 사본만 고치고 페이지에 옛 문장이 남으면 사람이 보는 소개가 없는 무료를 약속한다.
  it("클로버 문장은 출석 보상을 말하고 무료 사용량을 말하지 않는다", () => {
    const pageSource = Object.values(
      import.meta.glob<string>("../src/pages/about/ui/AboutPage.tsx", {
        query: "?raw",
        import: "default",
        eager: true,
      }),
    ).join("");
    const cloverSentence =
      "대화와 이미지 생성에는 클로버가 쓰여요. 클로버는 충전해서 쓰고, 매일 출석과 미션 보상으로도 받을 수 있어요.";

    expect(buildAboutBody()).toContain(cloverSentence);
    expect(buildAboutBody()).not.toContain("무료 사용량");
    expect(pageSource).toContain(cloverSentence);
    expect(pageSource).not.toContain("무료 사용량");
  });
});

describe("handleAboutMeta", () => {
  it("셸에 title·description·canonical을 주입해 200으로 돌려준다", async () => {
    const response = await handleAboutMeta(botRequest("/about"), createEnv());
    const html = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(
      "text/html; charset=utf-8",
    );
    expect(html).toContain("<title>서비스 소개 — 또나</title>");
    expect(html).toContain(
      '<link rel="canonical" href="https://ddona.example/about" />',
    );
    expect(html).toContain('<div id="root"><main><h1>서비스 소개</h1>');
    expect(html).toContain('<a href="mailto:contact@ddona.site">');
  });

  it("빈 #root가 없으면 본문 없이 head만 넣는다", async () => {
    const env = createEnv({
      ASSETS: {
        fetch: () =>
          Promise.resolve(new Response(SHELL_HTML.replace('<div id="root"></div>', '<div id="app"></div>'))),
      },
    });
    const html = await (await handleAboutMeta(botRequest("/about"), env)).text();

    expect(html).toContain("<title>서비스 소개 — 또나</title>");
    expect(html).not.toContain("<main>");
  });

  it("PUBLIC_ORIGIN이 없으면 요청 오리진으로 폴백한다 (로컬 개발)", async () => {
    const response = await handleAboutMeta(
      botRequest("/about"),
      createEnv({ PUBLIC_ORIGIN: undefined }),
    );
    const html = await response.text();

    expect(html).toContain(
      '<link rel="canonical" href="https://ddona.local/about" />',
    );
  });
});
