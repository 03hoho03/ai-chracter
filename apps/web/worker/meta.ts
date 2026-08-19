import { escapeHtml } from "./html";

/**
 * <head>에 넣을 메타. 전부 선택이다 — 상세 페이지는 전 항목을 채우지만
 * 홈은 index.html에 이미 박혀 있는 것 말고 canonical·og:url만 주입한다(US-009).
 */
export interface PageMeta {
  title?: string;
  description?: string;
  canonical?: string;
  /** 공유 미리보기는 되게 하되 색인은 막을 때(프로필 페이지) `"noindex"`. */
  robots?: string;
  ogTitle?: string;
  ogDescription?: string;
  ogImage?: string;
  ogUrl?: string;
  ogType?: string;
  ogSiteName?: string;
  twitterCard?: string;
}

/** 이름·속성명은 아래 상수뿐이라 이스케이프가 필요 없고, content는 전부 사용자 입력일 수 있다. */
function metaByName(name: string, content: string | undefined): string | null {
  if (content === undefined) return null;
  return `<meta name="${name}" content="${escapeHtml(content)}" />`;
}

function metaByProperty(
  property: string,
  content: string | undefined,
): string | null {
  if (content === undefined) return null;
  return `<meta property="${property}" content="${escapeHtml(content)}" />`;
}

/**
 * 메타 태그 문자열을 만든다. 값이 주어진 항목만 태그가 되고, 모든 값은 `escapeHtml`을 통과한다.
 * 결과는 `injectHead`로 index.html에 끼워 넣는다.
 */
export function buildMetaTags(meta: PageMeta): string {
  const tags = [
    meta.title === undefined
      ? null
      : `<title>${escapeHtml(meta.title)}</title>`,
    metaByName("description", meta.description),
    meta.canonical === undefined
      ? null
      : `<link rel="canonical" href="${escapeHtml(meta.canonical)}" />`,
    metaByName("robots", meta.robots),
    metaByProperty("og:title", meta.ogTitle),
    metaByProperty("og:description", meta.ogDescription),
    metaByProperty("og:image", meta.ogImage),
    metaByProperty("og:url", meta.ogUrl),
    metaByProperty("og:type", meta.ogType),
    metaByProperty("og:site_name", meta.ogSiteName),
    metaByName("twitter:card", meta.twitterCard),
  ];

  return tags.filter((tag) => tag !== null).join("\n");
}
