import { fetchApiJson, isRecord, isUuid, isViewableByCrawler } from "./api";
import { readAppShellHtml, serveAppShell } from "./appShell";
import { buildJsonLd, injectHead } from "./html";
import { buildMetaTags, SITE_NAME, toMetaDescription } from "./meta";
import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./workerRuntime";

/**
 * `/content/{type}/{id}`. `{type}`은 URL 가독성용 세그먼트일 뿐 조회에 쓰이지 않으므로
 * (`GET /contents/{id}`가 type을 포함해 응답한다) 여기서도 값을 검사하지 않고 흘린다.
 * canonical은 응답의 type으로 만들어 `/content/story/{캐릭터id}` 같은 주소를 한 곳으로 모은다.
 */
const CONTENT_PATH = /^\/content\/[^/]+\/([^/]+)$/;

/** 경로 → 콘텐츠 id. 콘텐츠 상세 경로가 아니면 `undefined`. 순수 함수다. */
export function parseContentPath(pathname: string): string | undefined {
  const match = CONTENT_PATH.exec(pathname);
  if (match === null) return undefined;

  const [, id] = match;
  return id;
}

/** 메타를 만드는 데 실제로 쓰는 필드만 추린 콘텐츠. */
export type ContentMetaSource = {
  id: string;
  type: string;
  name: string;
  oneLiner: string;
  detailDescription: string;
  creatorNickname: string;
};

/** 한 줄 소개 우선, 없으면 상세 설명 앞부분. */
function toDescription(content: ContentMetaSource): string | undefined {
  return toMetaDescription(
    content.oneLiner.trim() === ""
      ? content.detailDescription
      : content.oneLiner,
  );
}

/**
 * 봇에게 내려보낼 <head> 조각(메타 태그 + JSON-LD)을 만든다. 순수 함수다.
 *
 * 사용자 입력(이름·소개·닉네임)은 `buildMetaTags`의 `escapeHtml`과 `buildJsonLd`를
 * 통과한다 — 여기서 태그 문자열을 직접 조립하지 말 것(그 자리가 곧 XSS 누락 지점이다).
 */
export function buildContentHead(
  content: ContentMetaSource,
  origin: string,
): string {
  const canonical = `${origin}/content/${content.type}/${content.id}`;
  const imageUrl = `${origin}/og/content/${content.id}.jpg`;
  const description = toDescription(content);

  const tags = buildMetaTags({
    title: `${content.name} — ${SITE_NAME}`,
    description,
    canonical,
    ogTitle: content.name,
    ogDescription: description,
    ogImage: imageUrl,
    ogUrl: canonical,
    ogType: "article",
    ogSiteName: SITE_NAME,
    // 썸네일이 768x1024 세로 비율이라 summary_large_image는 위아래가 잘린다.
    twitterCard: "summary",
  });

  const jsonLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "CreativeWork",
    name: content.name,
    description,
    url: canonical,
    image: imageUrl,
  };
  if (content.creatorNickname !== "") {
    jsonLd.author = { "@type": "Person", name: content.creatorNickname };
  }

  return `${tags}\n${buildJsonLd(jsonLd)}`;
}

/**
 * 콘텐츠 조회 결과.
 *
 * `notFound`(없음·비공개·삭제)와 `unavailable`(API 장애·타임아웃·형식 파손)을 반드시
 * 나눈다 — 장애를 404로 번역하면 검색엔진이 장애 중에 페이지를 색인에서 지운다.
 */
type ContentResolution =
  | { kind: "ok"; content: ContentMetaSource }
  | { kind: "notFound" }
  | { kind: "unavailable" };

function toText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function toContentMetaSource(
  data: Record<string, unknown>,
  id: string,
): ContentMetaSource | undefined {
  // 이름과 타입이 없으면 주입할 게 없다 — 빈 제목을 내보내느니 주입을 건너뛴다.
  if (typeof data.name !== "string" || typeof data.type !== "string") {
    return undefined;
  }

  return {
    id,
    type: data.type,
    name: data.name,
    oneLiner: toText(data.oneLiner),
    detailDescription: toText(data.detailDescription),
    creatorNickname: toText(data.creatorNickname),
  };
}

async function resolveContent(
  env: WorkerEnv,
  id: string,
): Promise<ContentResolution> {
  const result =
    env.API_BASE_URL === undefined
      ? ({ kind: "unavailable" } as const)
      : await fetchApiJson(env.API_BASE_URL, `/contents/${id}`);
  if (result.kind !== "ok") return { kind: result.kind };

  const { data } = result;
  // 응답 형식이 예상 밖이면 404가 아니라 장애로 친다 — 스키마가 바뀐 날 전 콘텐츠를
  // 한꺼번에 색인에서 지우는 것보다 주입 없는 200으로 버티는 편이 낫다.
  if (!isRecord(data) || !isRecord(data.accessStatus)) {
    return { kind: "unavailable" };
  }
  if (!isViewableByCrawler(data.accessStatus)) return { kind: "notFound" };

  const content = toContentMetaSource(data, id);
  return content === undefined
    ? { kind: "unavailable" }
    : { kind: "ok", content };
}

/**
 * 봇 UA + `/content/{type}/{id}` — index.html의 <head>를 채워 응답한다.
 *
 * 일반 사용자는 이 경로를 타지 않는다(호출부에서 `isCrawler`로 가른다) — 주입 내용이
 * React가 클라이언트에서 만드는 것과 같으므로 클로킹이 아니고, 사용자 TTFB는 그대로여야 한다.
 */
export async function handleContentMeta(
  request: Request,
  env: WorkerEnv,
  id: string,
): Promise<Response> {
  if (!isUuid(id)) return serveAppShell(request, env, 404);

  const resolved = await resolveContent(env, id);
  if (resolved.kind === "notFound") return serveAppShell(request, env, 404);
  // API 장애·타임아웃엔 주입 없이 원본 셸을 200으로 준다 — 봇에게 500도 404도 주지 않는다.
  if (resolved.kind === "unavailable") return serveAppShell(request, env);

  const html = await readAppShellHtml(request, env);
  const origin = resolvePublicOrigin(env, request);
  const head = buildContentHead(resolved.content, origin);

  return new Response(injectHead(html, head), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
