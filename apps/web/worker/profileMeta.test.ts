import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildProfileHead,
  handleProfileMeta,
  parseProfilePath,
  type ProfileMetaSource,
} from "./profileMeta";
import type { WorkerEnv } from "./workerRuntime";

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
  overrides: Partial<ProfileMetaSource> = {},
): ProfileMetaSource {
  return { id: ID, nickname: "달빛작가", bio: "밤에만 씁니다", ...overrides };
}

/** 실제 `GET /users/{id}/profile` 응답에서 이 모듈이 읽는 필드만 담은 본문. */
function createProfileBody(overrides: Record<string, unknown> = {}) {
  return {
    nickname: "달빛작가",
    bio: "밤에만 씁니다",
    profileImageAssetId: null,
    profileImageUrl: null,
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

function botRequest(path = `/profile/${ID}`): Request {
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

describe("parseProfilePath", () => {
  it("프로필 경로에서 사용자 id를 뽑는다", () => {
    expect(parseProfilePath(`/profile/${ID}`)).toBe(ID);
  });

  it("세그먼트 수가 다르면 프로필 경로가 아니다", () => {
    expect(parseProfilePath("/profile")).toBeUndefined();
    expect(parseProfilePath("/profile/")).toBeUndefined();
    expect(parseProfilePath(`/profile/${ID}/edit`)).toBeUndefined();
    expect(parseProfilePath(`/content/character/${ID}`)).toBeUndefined();
  });
});

describe("buildProfileHead", () => {
  const origin = "https://ddona.example";

  it("title은 `{닉네임} — 또나`, og:title은 닉네임이다", () => {
    const head = buildProfileHead(createSource(), origin);

    expect(head).toContain("<title>달빛작가 — 또나</title>");
    expect(head).toContain('<meta property="og:title" content="달빛작가" />');
    expect(head).toContain('<meta property="og:site_name" content="또나" />');
  });

  it("noindex를 함께 주입한다 — 미리보기는 되게 하되 색인은 막는다", () => {
    expect(buildProfileHead(createSource(), origin)).toContain(
      '<meta name="robots" content="noindex" />',
    );
  });

  it("og:type은 profile, og:image는 사용자 og 프록시 절대 URL이다", () => {
    const head = buildProfileHead(createSource(), origin);

    expect(head).toContain('<meta property="og:type" content="profile" />');
    expect(head).toContain(
      `<meta property="og:image" content="${origin}/og/user/${ID}.jpg" />`,
    );
    expect(head).toContain(
      `<meta property="og:url" content="${origin}/profile/${ID}" />`,
    );
    expect(head).toContain('<meta name="twitter:card" content="summary" />');
  });

  it("색인하지 않을 페이지라 canonical을 두지 않는다", () => {
    expect(buildProfileHead(createSource(), origin)).not.toContain(
      'rel="canonical"',
    );
  });

  it("description은 bio를 쓴다", () => {
    const head = buildProfileHead(createSource(), origin);

    expect(head).toContain(
      '<meta name="description" content="밤에만 씁니다" />',
    );
    expect(head).toContain(
      '<meta property="og:description" content="밤에만 씁니다" />',
    );
  });

  it("bio가 비면 `{닉네임}님의 캐릭터`로 떨어진다", () => {
    const head = buildProfileHead(createSource({ bio: "  " }), origin);

    expect(head).toContain(
      '<meta name="description" content="달빛작가님의 캐릭터" />',
    );
  });

  it("bio를 160자로 자른다", () => {
    const head = buildProfileHead(
      createSource({ bio: "가".repeat(300) }),
      origin,
    );

    const match = /<meta name="description" content="([^"]*)" \/>/.exec(head);
    expect(match?.[1]).toBe(`${"가".repeat(159)}…`);
  });

  it("닉네임과 bio가 이스케이프를 통과한다 — 둘 다 사용자 입력이다", () => {
    const head = buildProfileHead(
      createSource({
        nickname: '"><script>alert(1)</script>',
        bio: '" onload="x',
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
});

describe("handleProfileMeta", () => {
  it("정상 응답이면 셸의 <head>에 메타를 주입한다", async () => {
    const fetchMock = stubJson(createProfileBody());

    const response = await handleProfileMeta(botRequest(), createEnv(), ID);
    const html = await response.text();

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(
      "text/html; charset=utf-8",
    );
    expect(html).toContain("<title>달빛작가 — 또나</title>");
    expect(html).toContain('<meta name="robots" content="noindex" />');
    expect(html).toContain(
      `<meta property="og:image" content="https://ddona.example/og/user/${ID}.jpg" />`,
    );
    // index.html에 박힌 홈 title은 같은 키라 교체된다(중복 title을 남기지 않는다).
    expect(html).not.toContain("<title>또나 — AI 캐릭터 챗</title>");
    expect(html).toContain('<div id="root">');
  });

  it("API를 `/users/{id}/profile`로 부른다", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", (input: string | URL | Request) => {
      urls.push(String(input));
      return Promise.resolve(
        new Response(JSON.stringify(createProfileBody()), {
          headers: { "content-type": "application/json" },
        }),
      );
    });

    await handleProfileMeta(botRequest(), createEnv(), ID);

    expect(urls).toEqual([`https://api.example.com/users/${ID}/profile`]);
  });

  it("UUID가 아니면 API를 부르지 않고 404다", async () => {
    const fetchMock = stubJson(createProfileBody());

    const response = await handleProfileMeta(
      botRequest("/profile/me"),
      createEnv(),
      "me",
    );

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("없거나 탈퇴한 사용자는 404다 — 닉네임이 새어 나가지 않는다", async () => {
    stubJson({ detail: "User not found" }, 404);

    const response = await handleProfileMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain("달빛작가");
  });

  it("API가 5xx면 404가 아니라 주입 없는 200이다 — 장애를 색인 삭제로 번역하지 않는다", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    stubJson({ detail: "boom" }, 503);

    const response = await handleProfileMeta(botRequest(), createEnv(), ID);

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

    const response = await handleProfileMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(200);
    expect(await response.text()).not.toContain("달빛작가");
  });

  it("응답 형식이 예상 밖이면 404가 아니라 주입 없는 200이다", async () => {
    stubJson({ profileImageUrl: null });

    const response = await handleProfileMeta(botRequest(), createEnv(), ID);

    expect(response.status).toBe(200);
  });

  it("PUBLIC_ORIGIN이 없으면 요청 오리진으로 URL을 만든다", async () => {
    stubJson(createProfileBody());

    const response = await handleProfileMeta(
      new Request(`http://localhost:5174/profile/${ID}`),
      createEnv({ PUBLIC_ORIGIN: undefined }),
      ID,
    );

    expect(await response.text()).toContain(
      `content="http://localhost:5174/og/user/${ID}.jpg"`,
    );
  });
});
