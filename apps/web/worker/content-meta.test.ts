import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildContentHead,
  handleContentMeta,
  parseContentPath,
  type ContentMetaSource,
} from "./content-meta";
import type { WorkerEnv } from "./types";

const ID = "11111111-2222-4333-8444-555555555555";

const SHELL_HTML = `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <title>또나 — AI 캐릭터 챗</title>
  </head>
  <body><div id="root"></div></body>
</html>
`;

function createSource(
  overrides: Partial<ContentMetaSource> = {},
): ContentMetaSource {
  return {
    id: ID,
    type: "character",
    name: "루나",
    oneLiner: "달빛 마녀",
    detailDescription: "달빛을 다루는 마녀다.",
    creatorNickname: "제작자",
    ...overrides,
  };
}

/** 실제 `GET /contents/{id}` 응답에서 이 모듈이 읽는 필드만 담은 본문. */
function createDetailBody(overrides: Record<string, unknown> = {}) {
  return {
    id: ID,
    type: "character",
    name: "루나",
    oneLiner: "달빛 마녀",
    detailDescription: "달빛을 다루는 마녀다.",
    creatorNickname: "제작자",
    accessStatus: { kind: "accessible", visibility: "public" },
    ...overrides,
  };
}

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

function botRequest(path = `/content/character/${ID}`): Request {
  return new Request(`https://ddona.example${path}`, {
    headers: { "user-agent": "facebookexternalhit/1.1" },
  });
}

function stubJson(body: unknown, status = 200) {
  const fetchMock = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("parseContentPath", () => {
  it("콘텐츠 상세 경로에서 id를 뽑는다", () => {
    expect(parseContentPath(`/content/character/${ID}`)).toBe(ID);
    expect(parseContentPath(`/content/story/${ID}`)).toBe(ID);
  });

  it("세그먼트 수가 다르면 콘텐츠 경로가 아니다", () => {
    expect(parseContentPath("/content/character")).toBeNull();
    expect(parseContentPath(`/content/character/${ID}/extra`)).toBeNull();
    expect(parseContentPath(`/content/character/${ID}/`)).toBeNull();
    expect(parseContentPath("/profile/me")).toBeNull();
  });
});

describe("buildContentHead", () => {
  const origin = "https://ddona.example";

  it("title은 `{이름} — 또나`, og:site_name은 또나다", () => {
    const head = buildContentHead(createSource(), origin);

    expect(head).toContain("<title>루나 — 또나</title>");
    expect(head).toContain('<meta property="og:site_name" content="또나" />');
    // og:title은 접미사 없는 이름 — 미리보기 카드가 사이트명을 따로 보여 준다.
    expect(head).toContain('<meta property="og:title" content="루나" />');
  });

  it("canonical·og:url·og:image가 PUBLIC_ORIGIN 기준 절대 URL이다", () => {
    const head = buildContentHead(createSource(), origin);

    expect(head).toContain(
      `<link rel="canonical" href="${origin}/content/character/${ID}" />`,
    );
    expect(head).toContain(
      `<meta property="og:url" content="${origin}/content/character/${ID}" />`,
    );
    expect(head).toContain(
      `<meta property="og:image" content="${origin}/og/content/${ID}.jpg" />`,
    );
  });

  it("canonical의 type은 URL이 아니라 API 응답의 type을 따른다", () => {
    const head = buildContentHead(createSource({ type: "story" }), origin);

    expect(head).toContain(`href="${origin}/content/story/${ID}"`);
  });

  it("twitter:card는 summary다 — 세로 썸네일이 large에서 잘린다", () => {
    expect(buildContentHead(createSource(), origin)).toContain(
      '<meta name="twitter:card" content="summary" />',
    );
  });

  it("description은 oneLiner를 쓴다", () => {
    const head = buildContentHead(createSource(), origin);

    expect(head).toContain('<meta name="description" content="달빛 마녀" />');
    expect(head).toContain(
      '<meta property="og:description" content="달빛 마녀" />',
    );
  });

  it("oneLiner가 비면 detailDescription으로 떨어지고 줄바꿈은 공백이 된다", () => {
    const head = buildContentHead(
      createSource({ oneLiner: "  ", detailDescription: "첫 줄\n\n둘째 줄" }),
      origin,
    );

    expect(head).toContain(
      '<meta name="description" content="첫 줄 둘째 줄" />',
    );
  });

  it("description을 160자로 자른다", () => {
    const head = buildContentHead(
      createSource({ oneLiner: "가".repeat(300) }),
      origin,
    );

    const match = /<meta name="description" content="([^"]*)" \/>/.exec(head);
    expect(match?.[1]).toBe(`${"가".repeat(159)}…`);
  });

  it("소개가 전혀 없으면 description 태그 자체를 만들지 않는다", () => {
    const head = buildContentHead(
      createSource({ oneLiner: "", detailDescription: "" }),
      origin,
    );

    expect(head).not.toContain('name="description"');
    expect(head).not.toContain("og:description");
  });

  it("사용자 입력이 전부 이스케이프된다", () => {
    const head = buildContentHead(
      createSource({
        name: '"><script>alert(1)</script>',
        oneLiner: '" onload="x',
      }),
      origin,
    );

    expect(head).not.toContain("<script>alert(1)</script>");
    expect(head).not.toContain('onload="x');
    expect(head).toContain(
      "<title>&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt; — 또나</title>",
    );
    expect(head).toContain('content="&quot; onload=&quot;x"');
  });

  it("JSON-LD(CreativeWork)를 함께 만든다 — `</script>` 탈출은 막힌다", () => {
    const head = buildContentHead(
      createSource({ name: "</script><img src=x>" }),
      origin,
    );

    expect(head).toContain('<script type="application/ld+json">');
    expect(head).toContain('"@type":"CreativeWork"');
    expect(head).toContain(`"url":"${origin}/content/character/${ID}"`);
    expect(head).toContain('"author":{"@type":"Person","name":"제작자"}');
    expect(head).not.toContain("</script><img");
  });
});

describe("handleContentMeta", () => {
  it("정상 응답이면 셸의 <head>에 메타를 주입한다", async () => {
    stubJson(createDetailBody());

    const response = await handleContentMeta(botRequest(), createEnv(), ID);
    const html = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(
      "text/html; charset=utf-8",
    );
    expect(html).toContain("<title>루나 — 또나</title>");
    expect(html).toContain(
      `<meta property="og:image" content="https://ddona.example/og/content/${ID}.jpg" />`,
    );
    // index.html에 박힌 홈 title은 같은 키라 교체된다(중복 title을 남기지 않는다).
    expect(html).not.toContain("<title>또나 — AI 캐릭터 챗</title>");
    expect(html).toContain('<div id="root">');
  });

  it("UUID가 아니면 API를 부르지 않고 404다", async () => {
    const fetchMock = stubJson(createDetailBody());

    const response = await handleContentMeta(
      botRequest("/content/character/nope"),
      createEnv(),
      "nope",
    );

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("API가 404면 404다 — 없는 콘텐츠에 200을 주지 않는다(soft 404)", async () => {
    stubJson({ detail: "Not Found" }, 404);

    const response = await handleContentMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain("루나");
  });

  it("비공개 콘텐츠는 404이고 이름이 새어 나가지 않는다", async () => {
    stubJson(
      createDetailBody({
        accessStatus: { kind: "accessible", visibility: "private" },
      }),
    );

    const response = await handleContentMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain("루나");
  });

  it("링크 공개(link)는 통과시킨다 — 링크 공유 미리보기가 목적이다", async () => {
    stubJson(
      createDetailBody({
        accessStatus: { kind: "accessible", visibility: "link" },
      }),
    );

    const response = await handleContentMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(200);
    expect(await response.text()).toContain("<title>루나 — 또나</title>");
  });

  it("삭제·제한된 콘텐츠도 404다", async () => {
    stubJson(createDetailBody({ accessStatus: { kind: "deleted" } }));

    const response = await handleContentMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(404);
  });

  it("API가 5xx면 404가 아니라 주입 없는 200이다 — 장애를 색인 삭제로 번역하지 않는다", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    stubJson({ detail: "boom" }, 503);

    const response = await handleContentMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(200);
    expect(await response.text()).toContain(
      "<title>또나 — AI 캐릭터 챗</title>",
    );
  });

  it("API가 타임아웃이어도 주입 없는 200이다", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal("fetch", () =>
      Promise.reject(
        new DOMException("The operation was aborted", "TimeoutError"),
      ),
    );

    const response = await handleContentMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(200);
    expect(await response.text()).not.toContain("루나");
  });

  it("응답 형식이 예상 밖이면 404가 아니라 주입 없는 200이다", async () => {
    stubJson({ id: ID, accessStatus: { kind: "accessible" } });

    const response = await handleContentMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(200);
  });

  it("PUBLIC_ORIGIN이 없으면 요청 오리진으로 URL을 만든다", async () => {
    stubJson(createDetailBody());

    const response = await handleContentMeta(
      new Request(`http://localhost:5174/content/character/${ID}`),
      createEnv({ PUBLIC_ORIGIN: undefined }),
      ID,
    );

    expect(await response.text()).toContain(
      `content="http://localhost:5174/og/content/${ID}.jpg"`,
    );
  });
});
