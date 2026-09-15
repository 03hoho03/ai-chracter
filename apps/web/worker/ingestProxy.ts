import type { WorkerEnv } from "./workerRuntime";

/**
 * 브라우저 에러 ingest 경로 접두사(monitoring-techspec.md MT-3). web은 Bugsink(도커 내부
 * 네트워크, 포트 미게시)에 직접 못 닿으므로 이 Worker가 `api.ddona.site`(Caddy)로 중계하고,
 * Caddy가 같은 `/_ingest/*` 경로를 다시 bugsink로 넘긴다(`Caddyfile` 참조).
 *
 * 트레일링 슬래시 없는 `/_ingest` 단독은 프록시하지 않는다 — Caddy의 매처도 `/_ingest/*`라
 * 같은 경계를 쓴다(DEPLOY.md: 슬래시 없이 두드리면 이 라우트에 안 걸리고 api로 흘러 404).
 */
export const INGEST_PATH_PREFIX = "/_ingest/";

/**
 * 허용 메서드. envelope 수신은 POST뿐이지만(Sentry SDK가 항상 POST), Bugsink 관리자 UI는
 * `ddona.site` 경유로도 열람 가능해야 한다 — DEPLOY.md의 가입 차단 확인 절차가
 * `https://ddona.site/_ingest/accounts/signup/`을 **GET**으로 두드려 404를 확인한다(Caddy
 * 커밋 `fb92050`). 그래서 GET/HEAD(페이지 열람)·POST(envelope + 로그인 폼)만 통과시키고,
 * 이 경로가 쓸 일이 없는 나머지(PUT/PATCH/DELETE/OPTIONS/TRACE/CONNECT)는 익명 공개
 * 엔드포인트의 공격 표면을 줄이기 위해 405로 끝낸다.
 */
const ALLOWED_METHODS = new Set(["GET", "HEAD", "POST"]);

/**
 * 본문 크기 상한. Caddy가 같은 `{$SITE_ADDRESS}` 블록에 이미 `request_body { max_size 10MB }`를
 * 걸어 두었다(`Caddyfile`) — 그 숫자를 여기서 다시 정의하지 않고 그대로 맞춘다. Worker에서
 * 먼저 거르는 이유는 Caddy까지 보내지 않고 엣지에서 바로 끝내려는 것뿐이다(같은 값의 방어
 * 두 겹이지 별도 정책이 아니다).
 *
 * `Content-Length` 헤더만 본다(본문을 버퍼링하지 않는다) — 청크 전송처럼 헤더가 없는
 * 요청은 이 검사를 통과하고 Caddy의 상한이 최종 방어선이 된다.
 */
const MAX_BODY_BYTES = 10 * 1024 * 1024;

export function isIngestPath(pathname: string): boolean {
  return pathname.startsWith(INGEST_PATH_PREFIX);
}

function isTooLarge(request: Request): boolean {
  const contentLength = request.headers.get("content-length");
  if (contentLength === null) return false;
  return Number(contentLength) > MAX_BODY_BYTES;
}

function textResponse(status: number, body: string): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}

/**
 * `/_ingest/*` → `{API_BASE_URL}/_ingest/*`. 업스트림은 별도 변수를 두지 않고 기존
 * `API_BASE_URL`을 그대로 쓴다 — MT-3의 최종 결정이 이 경로를 새 서브도메인이 아니라
 * **기존 `api.ddona.site` 블록**에 얹는 것이었으므로(§0-1-21의 도커 내부 네트워크 제약 때문),
 * 이 프록시의 업스트림은 애초에 SEO 조회가 쓰는 업스트림과 같은 오리진이다. 둘을 별도
 * 변수로 쪼개면 실제로는 항상 같은 값을 손으로 두 번 맞춰야 하는 중복 설정이 생긴다.
 *
 * `X-Ingest-Secret`은 Worker가 붙인다 — 브라우저 번들에는 넣을 수 없는 값이라(공개 코드에
 * 시크릿을 심는 것과 같다) Worker 런타임 환경변수(`WorkerEnv.INGEST_SHARED_SECRET`)로만 받는다.
 * Caddy는 이 헤더를 envelope 경로(`/_ingest/api/{project_id}/envelope/`)에만 검사하고 나머지
 * `/_ingest/*`(관리자 UI)는 그대로 통과시키지만, 여기서는 경로를 가리지 않고 항상 붙인다 —
 * 조건을 나누는 것보다 항상 붙이는 쪽이 더 단순하고, 관리자 UI 쪽에서는 Caddy가 이 헤더를
 * 그냥 무시한다.
 */
export async function handleIngestProxy(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  if (!ALLOWED_METHODS.has(request.method)) {
    return textResponse(405, "Method Not Allowed");
  }

  if (isTooLarge(request)) {
    return textResponse(413, "Payload Too Large");
  }

  // WorkerEnv 필드는 전부 옵셔널이라 누락 시 런타임 에러가 아니라 조용히 undefined다
  // (workerRuntime.ts). 둘 다 있어야만 이 프록시가 의미가 있어서(어디로 보낼지 + 그
  // 업스트림이 요구하는 시크릿), 하나라도 없으면 시크릿 없이 반쪼가리로 전달하는 대신
  // 여기서 명시적으로 끝낸다 — 그러면 envelope 경로만 Caddy에서 401이 나 원인이 흐려진다.
  if (env.API_BASE_URL === undefined || env.INGEST_SHARED_SECRET === undefined) {
    console.warn(
      "[ingest] API_BASE_URL 또는 INGEST_SHARED_SECRET 런타임 환경변수가 없어 프록시를 건너뛴다",
    );
    return textResponse(500, "Ingest proxy is not configured");
  }

  const url = new URL(request.url);
  const upstreamUrl = `${env.API_BASE_URL.replace(/\/+$/, "")}${url.pathname}${url.search}`;

  const headers = new Headers(request.headers);
  headers.set("X-Ingest-Secret", env.INGEST_SHARED_SECRET);

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers,
      body: request.body,
    });
  } catch (error) {
    console.warn("[ingest] 업스트림 요청이 실패했다", error);
    return textResponse(502, "Ingest upstream unavailable");
  }

  // 본문·상태·헤더를 그대로 흘려보낸다(indexing.ts의 같은 패턴 — Response를 ResponseInit
  // 자리에 넣으면 status·headers가 통째로 복사된다).
  return new Response(upstream.body, upstream);
}
