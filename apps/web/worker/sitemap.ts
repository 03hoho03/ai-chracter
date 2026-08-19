import { isRecord } from "./api";
import { escapeHtml } from "./html";
import { resolvePublicOrigin } from "./origin";
import type { WorkerDeps, WorkerEnv } from "./types";

/** 상세 라우트가 있는 콘텐츠 타입. `/contents?type=` 쿼리값과 URL 세그먼트가 같은 문자열이다. */
const CONTENT_TYPES = ["character", "story"];

/**
 * 타입당 커서 순회 상한. API 한 페이지가 20건이므로 타입당 1,000건까지 담는다.
 * 상한에 걸리면 잘라내고 `console.warn`을 남긴다 — 조용히 누락시키지 않는다.
 */
const MAX_PAGES_PER_TYPE = 50;

const CACHE_MAX_AGE_SECONDS = 3600;

/**
 * API 실패로 홈만 담긴 최소 sitemap을 돌려줄 때의 캐시 수명.
 * 정상값(1시간)을 쓰면 몇 초짜리 API 장애가 한 시간 동안 고정된다.
 */
const FALLBACK_MAX_AGE_SECONDS = 60;

/**
 * URL 목록 → sitemap 0.9 XML. 순수 함수다.
 *
 * `<lastmod>`는 넣지 않는다 — 목록 API의 `ContentListItem`에 갱신 시각이 없고(백엔드를
 * 변경하지 않는다), 거짓 lastmod는 없는 것보다 나쁘다.
 */
export function buildSitemapXml(locations: string[]): string {
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...locations.map(
      (location) => `  <url><loc>${escapeHtml(location)}</loc></url>`,
    ),
    "</urlset>",
    "",
  ].join("\n");
}

/** `/contents` 응답에서 sitemap이 쓰는 두 가지(id 목록, 다음 커서)만 뽑는다. */
function parseContentListPage(
  payload: unknown,
): { ids: string[]; nextCursor: string | null } | null {
  if (!isRecord(payload) || !Array.isArray(payload.items)) return null;

  const ids: string[] = [];
  for (const item of payload.items) {
    if (isRecord(item) && typeof item.id === "string") ids.push(item.id);
  }

  const { nextCursor } = payload;
  return { ids, nextCursor: typeof nextCursor === "string" ? nextCursor : null };
}

/**
 * `GET {API_BASE_URL}/contents?type=...`를 커서로 끝까지 훑어 공개 콘텐츠 id를 모은다.
 *
 * 이 API가 이미 visibility=PUBLIC + moderation NORMAL + 발행됨만 내려주므로
 * (apps/api/src/api/content/router.py의 `list_contents`) 여기서 다시 거르지 않는다.
 * 한 페이지라도 실패하면 던진다 — 부분 목록을 정상 sitemap인 척 내보내지 않는다.
 */
async function fetchPublicContentIds(
  apiBaseUrl: string,
  type: string,
): Promise<string[]> {
  const endpoint = `${apiBaseUrl.replace(/\/+$/, "")}/contents?type=${type}`;
  const ids: string[] = [];
  let cursor: string | null = null;

  for (let page = 0; page < MAX_PAGES_PER_TYPE; page += 1) {
    const url =
      cursor === null
        ? endpoint
        : `${endpoint}&cursor=${encodeURIComponent(cursor)}`;
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`GET /contents?type=${type} → ${response.status}`);
    }

    const parsed = parseContentListPage(await response.json());
    if (parsed === null) {
      throw new Error(`GET /contents?type=${type} → 예상 밖의 응답 형식`);
    }

    ids.push(...parsed.ids);
    cursor = parsed.nextCursor;
    if (cursor === null) return ids;
  }

  console.warn(
    `[sitemap] type=${type} 순회가 ${MAX_PAGES_PER_TYPE}페이지 상한에 걸려 잘렸다 — 이후 콘텐츠가 sitemap에서 누락된다`,
  );
  return ids;
}

/** 홈 1건 + 타입별 공개 콘텐츠 전건. 한 타입이라도 실패하면 던진다. */
async function collectLocations(
  apiBaseUrl: string,
  origin: string,
): Promise<string[]> {
  const locations = [`${origin}/`];

  for (const type of CONTENT_TYPES) {
    const ids = await fetchPublicContentIds(apiBaseUrl, type);
    locations.push(...ids.map((id) => `${origin}/content/${type}/${id}`));
  }

  return locations;
}

/**
 * `GET /sitemap.xml`. Cache API로 1시간 캐시한다.
 *
 * API가 실패하면 500이 아니라 **홈만 담긴 최소 sitemap을 200으로** 돌려준다 —
 * 검색엔진이 sitemap 오류를 반복 관찰하면 재제출이 필요해진다.
 */
export async function handleSitemap(
  request: Request,
  env: WorkerEnv,
  deps: WorkerDeps,
): Promise<Response> {
  const cached = await deps.cache.match(request);
  if (cached !== undefined) return cached;

  const origin = resolvePublicOrigin(env, request);

  let locations: string[] | null = null;
  try {
    if (env.API_BASE_URL === undefined) {
      throw new Error("API_BASE_URL 런타임 환경변수가 없다");
    }
    locations = await collectLocations(env.API_BASE_URL, origin);
  } catch (error) {
    console.warn(
      "[sitemap] 콘텐츠 목록을 가져오지 못해 홈만 담은 최소 sitemap으로 응답한다",
      error,
    );
  }

  const isComplete = locations !== null;
  const maxAge = isComplete ? CACHE_MAX_AGE_SECONDS : FALLBACK_MAX_AGE_SECONDS;
  const response = new Response(buildSitemapXml(locations ?? [`${origin}/`]), {
    headers: {
      "content-type": "application/xml; charset=utf-8",
      "cache-control": `public, max-age=${maxAge}`,
    },
  });

  // 실패 폴백은 캐시에 넣지 않는다 — 넣으면 잠깐의 API 장애가 한 시간짜리 빈 sitemap이 된다.
  if (isComplete) await deps.cache.put(request, response.clone());

  return response;
}
