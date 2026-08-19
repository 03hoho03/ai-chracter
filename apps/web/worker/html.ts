/**
 * HTML에 문자열을 끼워 넣기 전에 항상 통과시키는 단일 이스케이프.
 *
 * **텍스트 컨텍스트와 속성 컨텍스트를 분기하지 않는다** — 캐릭터 이름·소개·닉네임·bio가 전부
 * 사용자 입력인데 이걸 <head>에 문자열로 결합하므로, 분기가 생기는 순간 그 분기 자체가
 * 누락 지점이 된다. 다섯 문자를 모두 엔티티로 바꾸면 두 컨텍스트 어디서도 탈출할 수 없다.
 *
 * 값 하나에 **정확히 한 번만** 적용한다(두 번 적용하면 `&`가 `&amp;amp;`로 이중 이스케이프된다).
 */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * JSON-LD를 `<script type="application/ld+json">`으로 감싼다.
 *
 * `<`를 전부 `<`로 바꿔 `</script>`를 무력화한다(JSON 문자열 안에서 유효한 이스케이프라
 * 파서가 읽는 값은 그대로다). 닫는 태그만 막으면 `<!--`가 남으므로 시퀀스가 아니라 문자를 막는다.
 */
export function buildJsonLd(data: unknown): string {
  const json = JSON.stringify(data).replace(/</g, "\\u003c");
  return `<script type="application/ld+json">${json}</script>`;
}

/** head에서 우리가 덮어쓸 수 있는 태그. 뒤의 `\s*`는 지울 때 빈 줄을 남기지 않기 위한 것. */
const OVERRIDABLE_HEAD_TAG =
  /(?:<title\b[^>]*>[\s\S]*?<\/title>|<meta\b[^>]*>|<link\b[^>]*>)\s*/gi;

function attributeValue(tag: string, attribute: string): string | null {
  const match = new RegExp(`\\s${attribute}="([^"]*)"`, "i").exec(tag);
  if (!match) return null;

  const [, value] = match;
  return value ?? null;
}

/**
 * 태그를 "같은 자리를 차지하는가"로 식별하는 키. 키가 없으면(charset·viewport·stylesheet 등)
 * 우리가 건드리지 않는 태그다.
 */
function headTagKey(tag: string): string | null {
  if (/^<title\b/i.test(tag)) return "title";
  if (/^<link\b/i.test(tag)) {
    return attributeValue(tag, "rel") === "canonical" ? "canonical" : null;
  }

  const name = attributeValue(tag, "name");
  if (name !== null) return `name:${name}`;

  const property = attributeValue(tag, "property");
  return property !== null ? `property:${property}` : null;
}

function headTagKeys(html: string): Set<string> {
  const keys = new Set<string>();
  for (const tag of html.match(OVERRIDABLE_HEAD_TAG) ?? []) {
    const key = headTagKey(tag);
    if (key !== null) keys.add(key);
  }
  return keys;
}

/**
 * index.html 문자열의 `</head>` 앞에 메타 문자열을 끼워 넣는다.
 *
 * 넣기 전에 **주입할 태그와 같은 키를 가진 기존 태그를 지운다** — index.html에는 홈 기준
 * title·og:*가 이미 박혀 있고(US-009), 크롤러 대부분은 중복된 og 속성에서 앞의 것을 쓰기
 * 때문에 그냥 덧붙이면 상세 페이지 미리보기가 홈 문구로 나간다. 키가 겹치지 않는 태그는
 * (홈이 canonical·og:url만 주입할 때의 og:title 등) 그대로 남는다.
 *
 * `</head>`가 없으면 원본을 그대로 돌려준다 — 넣을 자리를 모르는 채로 HTML을 망가뜨리지 않는다.
 */
export function injectHead(html: string, headHtml: string): string {
  const closeHeadIndex = html.search(/<\/head>/i);
  if (closeHeadIndex === -1) return html;

  const injectedKeys = headTagKeys(headHtml);
  const head = html
    .slice(0, closeHeadIndex)
    .replace(OVERRIDABLE_HEAD_TAG, (tag) => {
      const key = headTagKey(tag);
      return key !== null && injectedKeys.has(key) ? "" : tag;
    });

  // `html.replace("</head>", ...)`가 아니라 슬라이스로 이어붙인다 — headHtml에는 사용자 입력이
  // 들어 있고, 치환 문자열 안의 `$&`·`$1`은 replace가 해석해 버린다.
  return `${head}${headHtml}\n${html.slice(closeHeadIndex)}`;
}
