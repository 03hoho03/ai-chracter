import { escapeHtml } from "./html";

/** 브랜드명. 한글이 정식 표기다(로마자 ddona는 도메인·식별자에만 쓴다). */
export const SITE_NAME = "또나";

/**
 * <head>에 넣을 메타. 전부 선택이다 — 상세 페이지는 전 항목을 채우지만
 * 홈은 index.html에 이미 박혀 있는 것 말고 canonical·og:url만 주입한다(US-009).
 */
export type PageMeta = {
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
};

/** 이름·속성명은 아래 상수뿐이라 이스케이프가 필요 없고, content는 전부 사용자 입력일 수 있다. */
function metaByName(
  name: string,
  content: string | undefined,
): string | undefined {
  if (content === undefined) return undefined;
  return `<meta name="${name}" content="${escapeHtml(content)}" />`;
}

function metaByProperty(
  property: string,
  content: string | undefined,
): string | undefined {
  if (content === undefined) return undefined;
  return `<meta property="${property}" content="${escapeHtml(content)}" />`;
}

/**
 * 메타 태그 문자열을 만든다. 값이 주어진 항목만 태그가 되고, 모든 값은 `escapeHtml`을 통과한다.
 * 결과는 `injectHead`로 index.html에 끼워 넣는다.
 */
export function buildMetaTags(meta: PageMeta): string {
  const tags = [
    meta.title === undefined
      ? undefined
      : `<title>${escapeHtml(meta.title)}</title>`,
    metaByName("description", meta.description),
    meta.canonical === undefined
      ? undefined
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

  return tags.filter((tag) => tag !== undefined).join("\n");
}

/**
 * description 최대 길이. 구글은 픽셀 폭으로 자르지만 카카오·페이스북 미리보기는
 * 문자 수로 자른다 — 어차피 잘릴 뒤쪽을 통째로 실어 보내지 않는다.
 */
const DESCRIPTION_MAX_LENGTH = 160;

/**
 * 사용자 입력을 description 값으로 다듬는다. 줄바꿈을 공백으로 눕히고 160자로 자른다.
 * 남는 게 없으면 `undefined`를 줘서 빈 description 태그를 만들지 않게 한다.
 */
export function toMetaDescription(source: string): string | undefined {
  const text = source.replace(/\s+/g, " ").trim();

  if (text === "") return undefined;
  if (text.length <= DESCRIPTION_MAX_LENGTH) return text;
  return `${text.slice(0, DESCRIPTION_MAX_LENGTH - 1).trimEnd()}…`;
}
