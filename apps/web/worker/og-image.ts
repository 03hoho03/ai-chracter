import {
  fetchApiJson,
  isRecord,
  isUuid,
  isViewableByCrawler,
} from "./api";
import type { WorkerDeps, WorkerEnv } from "./types";

/**
 * og:image 프록시의 경로 접두사.
 *
 * 바깥(카카오·페이스북의 og 캐시)에 노출되는 주소는 **만료되지 않아야 한다**. 썸네일의
 * presigned URL은 금방 만료되는데 크롤러는 og:image를 자기 서버로 긁어가 몇 달씩
 * 캐시하므로, 만료되는 URL을 그대로 내보내면 미리보기 이미지가 영구히 비어 버린다.
 * 그래서 presigned URL은 이 Worker 안에서만 쓰고 버린다.
 */
export const OG_IMAGE_PATH_PREFIX = "/og/";

/** `/og/{content|user}/{uuid}.jpg` */
const OG_IMAGE_PATH = /^\/og\/(content|user)\/([^/]+)\.jpg$/;

const CACHE_MAX_AGE_SECONDS = 86400;

/**
 * API 장애로 기본 이미지를 대신 내보낼 때의 캐시 수명.
 * 정상값(24시간)을 쓰면 몇 초짜리 장애가 하루짜리 "썸네일 없는 미리보기"가 된다.
 */
const FALLBACK_MAX_AGE_SECONDS = 60;

/** US-001의 브랜드 기본 이미지. 썸네일이 없는 콘텐츠의 미리보기가 여기로 떨어진다. */
const DEFAULT_IMAGE_PATH = "/og-default.png";

export interface OgImageTarget {
  kind: "content" | "user";
  id: string;
}

/**
 * 경로 → 프록시 대상. 순수 함수다.
 *
 * UUID가 아니면 여기서 `null`이 되어 API를 두드리지 않는다 — 아무 문자열이나 왕복을
 * 만들면 크롤러가 곧 API 부하가 된다.
 */
export function parseOgImagePath(pathname: string): OgImageTarget | null {
  const match = OG_IMAGE_PATH.exec(pathname);
  if (match === null) return null;

  const [, kind, id] = match;
  if (id === undefined || !isUuid(id)) return null;

  return { kind: kind === "content" ? "content" : "user", id };
}

/**
 * 원본 이미지를 어디서 가져올지에 대한 판정.
 *
 * `missing`(썸네일 없음, 확정)과 `unavailable`(API 장애, 일시적)을 나누는 이유는 캐시
 * 수명이 다르기 때문이다 — 확정된 폴백은 오래 캐시해도 되지만 장애 폴백은 안 된다.
 */
type ImageSource =
  | { kind: "url"; url: string }
  | { kind: "missing" }
  | { kind: "notFound" }
  | { kind: "unavailable" };

function toImageSource(rawUrl: unknown): ImageSource {
  if (typeof rawUrl !== "string" || rawUrl === "") return { kind: "missing" };
  return { kind: "url", url: rawUrl };
}

async function resolveContentImage(
  apiBaseUrl: string,
  id: string,
): Promise<ImageSource> {
  const result = await fetchApiJson(apiBaseUrl, `/contents/${id}`);
  if (result.kind !== "ok") return { kind: result.kind };

  const { data } = result;
  // 응답 형식이 예상 밖이면 404가 아니라 장애로 친다 — 스키마가 바뀐 날 전 콘텐츠의
  // 미리보기 이미지를 한꺼번에 잃는 것보다 기본 이미지로 버티는 편이 낫다.
  if (!isRecord(data) || !isRecord(data.accessStatus)) {
    return { kind: "unavailable" };
  }
  if (!isViewableByCrawler(data.accessStatus)) return { kind: "notFound" };

  return toImageSource(data.thumbnailUrl);
}

async function resolveUserImage(
  apiBaseUrl: string,
  id: string,
): Promise<ImageSource> {
  // 탈퇴·삭제된 사용자는 API가 404를 준다(content/router.py의 `get_user_profile`).
  const result = await fetchApiJson(apiBaseUrl, `/users/${id}/profile`);
  if (result.kind !== "ok") return { kind: result.kind };

  const { data } = result;
  if (!isRecord(data)) return { kind: "unavailable" };

  return toImageSource(data.profileImageUrl);
}

function resolveImageSource(
  env: WorkerEnv,
  target: OgImageTarget,
): Promise<ImageSource> {
  if (env.API_BASE_URL === undefined) {
    console.warn(
      "[og] API_BASE_URL 런타임 환경변수가 없어 기본 이미지로 응답한다",
    );
    return Promise.resolve({ kind: "unavailable" });
  }

  return target.kind === "content"
    ? resolveContentImage(env.API_BASE_URL, target.id)
    : resolveUserImage(env.API_BASE_URL, target.id);
}

function notFound(): Response {
  return new Response("Not Found", {
    status: 404,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

/** 원본 응답의 본문은 그대로 흘려보내고 헤더만 우리 것으로 다시 쓴다. */
function toImageResponse(source: Response, maxAge: number): Response {
  return new Response(source.body, {
    status: 200,
    headers: {
      // Content-Type은 원본을 따른다 — 썸네일은 `_thumb.webp`라 `.jpg` 주소여도 webp다.
      "content-type": source.headers.get("content-type") ?? "image/png",
      "cache-control": `public, max-age=${maxAge}`,
    },
  });
}

async function fetchImage(url: string): Promise<Response | null> {
  let response: Response;
  try {
    response = await fetch(url);
  } catch (error) {
    console.warn("[og] 원본 이미지를 가져오지 못했다", error);
    return null;
  }

  if (!response.ok) {
    console.warn(`[og] 원본 이미지 → ${response.status}`);
    return null;
  }
  return response;
}

/**
 * 브랜드 기본 이미지로 폴백한다. 리다이렉트가 아니라 200으로 본문을 내려준다 —
 * og:image의 404·리다이렉트를 "이미지 없음"으로 굳혀 버리는 크롤러가 있다.
 *
 * `isSettled`가 false면(= API 장애) 짧게만 캐시하고 Cache API에는 넣지 않는다.
 */
async function serveDefaultImage(
  request: Request,
  env: WorkerEnv,
  deps: WorkerDeps,
  isSettled: boolean,
): Promise<Response> {
  const asset = await env.ASSETS.fetch(
    new Request(new URL(DEFAULT_IMAGE_PATH, request.url)),
  );
  const response = toImageResponse(
    asset,
    isSettled ? CACHE_MAX_AGE_SECONDS : FALLBACK_MAX_AGE_SECONDS,
  );

  if (isSettled) await deps.cache.put(request, response.clone());

  return response;
}

/**
 * `GET /og/{content|user}/{id}.jpg` — 만료되지 않는 og:image 주소.
 *
 * 404를 남발하지 않는다. 확실히 없는 대상(잘못된 id·비공개·삭제)에만 404를 주고,
 * 그 밖의 경우(썸네일 미설정, API 장애)에는 브랜드 기본 이미지를 200으로 내보낸다.
 */
export async function handleOgImage(
  request: Request,
  env: WorkerEnv,
  deps: WorkerDeps,
): Promise<Response> {
  const target = parseOgImagePath(new URL(request.url).pathname);
  if (target === null) return notFound();

  const cached = await deps.cache.match(request);
  if (cached !== undefined) return cached;

  const source = await resolveImageSource(env, target);
  if (source.kind === "notFound") return notFound();

  if (source.kind === "url") {
    const upstream = await fetchImage(source.url);
    if (upstream !== null) {
      const response = toImageResponse(upstream, CACHE_MAX_AGE_SECONDS);
      // 본문 스트림을 tee해야 하므로 clone이 필수다 — clone 없이 넣으면 본문이 캐시
      // 쪽에서 소비돼 호출자가 빈 응답을 받는다.
      await deps.cache.put(request, response.clone());
      return response;
    }
  }

  return serveDefaultImage(request, env, deps, source.kind === "missing");
}
