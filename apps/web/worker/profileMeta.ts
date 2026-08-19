import { fetchApiJson, isRecord, isUuid } from "./api";
import { readAppShellHtml, serveAppShell } from "./appShell";
import { injectHead } from "./html";
import { buildMetaTags, SITE_NAME, toMetaDescription } from "./meta";
import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./workerRuntime";

/** `/profile/{userId}`. 세그먼트가 하나뿐이라 콘텐츠 상세와 달리 정규화할 여지가 없다. */
const PROFILE_PATH = /^\/profile\/([^/]+)$/;

/** 경로 → 사용자 id. 프로필 경로가 아니면 `undefined`. 순수 함수다. */
export function parseProfilePath(pathname: string): string | undefined {
  const match = PROFILE_PATH.exec(pathname);
  if (match === null) return undefined;

  const [, id] = match;
  return id;
}

/** 메타를 만드는 데 실제로 쓰는 필드만 추린 프로필. */
export type ProfileMetaSource = {
  id: string;
  nickname: string;
  bio: string;
};

/**
 * 봇에게 내려보낼 <head> 조각을 만든다. 순수 함수다.
 *
 * 콘텐츠 상세와 달리 JSON-LD를 넣지 않는다 — 색인하지 않을 페이지라 구조화 데이터가
 * 갈 곳이 없다. 사용자 입력(닉네임·bio)은 `buildMetaTags`의 `escapeHtml`을 통과한다.
 */
export function buildProfileHead(
  profile: ProfileMetaSource,
  origin: string,
): string {
  const description =
    toMetaDescription(profile.bio) ??
    toMetaDescription(`${profile.nickname}님의 캐릭터`);

  return buildMetaTags({
    title: `${profile.nickname} — ${SITE_NAME}`,
    description,
    // 공유 미리보기는 되게 하되 검색 색인은 막는다 — 사용자가 공개 노출에 명시적으로
    // 동의한 적 없는 개인 페이지다(같은 이유로 sitemap에도 넣지 않는다).
    robots: "noindex",
    ogTitle: profile.nickname,
    ogDescription: description,
    ogImage: `${origin}/og/user/${profile.id}.jpg`,
    // canonical은 두지 않는다(noindex라 정규화할 대상이 아니다). og:url은 크롤러가
    // 미리보기 카드의 링크 주소로 쓰므로 정식 오리진 기준으로 준다.
    ogUrl: `${origin}/profile/${profile.id}`,
    ogType: "profile",
    ogSiteName: SITE_NAME,
    // 프로필 이미지는 정사각에 가깝고 원본이 없으면 브랜드 기본 이미지로 떨어진다.
    twitterCard: "summary",
  });
}

/**
 * 프로필 조회 결과.
 *
 * `notFound`(없는 사용자·탈퇴)와 `unavailable`(API 장애·타임아웃·형식 파손)을 반드시
 * 나눈다 — 장애를 404로 번역하면 검색엔진이 장애 중에 페이지를 색인에서 지운다.
 */
type ProfileResolution =
  | { kind: "ok"; profile: ProfileMetaSource }
  | { kind: "notFound" }
  | { kind: "unavailable" };

async function resolveProfile(
  env: WorkerEnv,
  id: string,
): Promise<ProfileResolution> {
  const result =
    env.API_BASE_URL === undefined
      ? ({ kind: "unavailable" } as const)
      : // 탈퇴·삭제된 사용자는 API가 404를 준다(content/router.py의 `get_user_profile`).
        await fetchApiJson(env.API_BASE_URL, `/users/${id}/profile`);
  if (result.kind !== "ok") return { kind: result.kind };

  const { data } = result;
  // 닉네임이 없으면 주입할 게 없다. 형식이 예상 밖인 것은 404가 아니라 장애로 친다 —
  // 스키마가 바뀐 날 프로필 전체를 색인에서 지우는 것보다 주입 없는 200이 낫다.
  if (!isRecord(data) || typeof data.nickname !== "string") {
    return { kind: "unavailable" };
  }

  return {
    kind: "ok",
    profile: {
      id,
      nickname: data.nickname,
      bio: typeof data.bio === "string" ? data.bio : "",
    },
  };
}

/**
 * 봇 UA + `/profile/{userId}` — index.html의 <head>를 채워 응답한다.
 *
 * 일반 사용자는 이 경로를 타지 않는다(호출부에서 `isCrawler`로 가른다) — 추가 API
 * 왕복 없이 지금처럼 200 + 클라이언트 렌더를 받는다.
 */
export async function handleProfileMeta(
  request: Request,
  env: WorkerEnv,
  id: string,
): Promise<Response> {
  if (!isUuid(id)) return serveAppShell(request, env, 404);

  const resolved = await resolveProfile(env, id);
  if (resolved.kind === "notFound") return serveAppShell(request, env, 404);
  // API 장애·타임아웃엔 주입 없이 원본 셸을 200으로 준다 — 봇에게 500도 404도 주지 않는다.
  if (resolved.kind === "unavailable") return serveAppShell(request, env);

  const html = await readAppShellHtml(request, env);
  const head = buildProfileHead(
    resolved.profile,
    resolvePublicOrigin(env, request),
  );

  return new Response(injectHead(html, head), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
