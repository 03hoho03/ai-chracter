// 웹 빌드(`dist/index.html` 과 그 자산)와 측정 서버의 런 묶음 응답을 `file://` 로 여는 HTML 한 장으로 굳힌다. 파일을 읽고 쓰는
// 것은 부르는 쪽(`exportStatic.mjs`)이 하고, 여기는 글만 다룬다.

import { STATIC_BUNDLE_ELEMENT_ID } from "../src/shared/api/staticBundleElement.ts";

/**
 * `<script type="application/json">` 안에 넣을 JSON 글. HTML 파서는 그 안에서 `</script`(대소문자 무관)를 만나면 요소를 닫고,
 * `<!--` 를 만나면 닫는 태그를 놓칠 수 있다. JSON 에서 `<` 는 문자열 안에만 나오므로 모두 `\u003c` 로 바꾸면 둘 다 사라지고,
 * `JSON.parse` 는 같은 값으로 읽는다.
 * @param {string} json
 * @returns {string}
 */
export function escapeJsonForHtml(json) {
  return json.replaceAll("<", "\\u003c");
}

/**
 * 인라인 `<script>` 안에 넣을 JS 코드. `</script`(대소문자 무관)와 `<!--` 의 `<` 를 `\x3C` 로 바꾼다. 그런 글은 문자열·템플릿
 * 글·정규식 안에만 나오고 `\x3C` 는 그 셋 모두에서 `<` 로 읽힌다(u 플래그 정규식 포함 — `<\!--` 는 u 플래그 정규식을 깨뜨린다).
 * @param {string} code
 * @returns {string}
 */
export function escapeScriptForHtml(code) {
  return code.replace(/<(?=\/script|!--)/gi, "\\x3C");
}

const MODULE_SCRIPT = /<script\b[^>]*\btype="module"[^>]*\bsrc="([^"]+)"[^>]*>\s*<\/script>/gi;
const STYLESHEET = /<link\b[^>]*\brel="stylesheet"[^>]*\bhref="([^"]+)"[^>]*\/?>/gi;
const EXTERNAL_REFERENCE = /\s(?:src|href)\s*=\s*["']?(?!data:)[^"'\s>]/i;

/**
 * 모듈 스크립트·스타일시트를 문서 안에 넣고, 런 묶음을 첫 앱 스크립트 바로 앞에 싣는다. 모듈 스크립트는 문서를 다 읽은 뒤에
 * 돌아 지금은 순서가 없어도 읽히지만, 실행 방식이 바뀌어도 앱이 읽을 때 데이터가 이미 있게 앞에 둔다.
 *
 * 넣지 못한 외부 참조(`modulepreload`·나뉜 청크 등)가 남으면 던진다 — `file://` 에서는 그 파일을 받지 못해 반쯤 빈 화면이 된다.
 * @param {{ indexHtml: string, readAsset: (href: string) => string, bundle: unknown }} input
 * @returns {string}
 */
export function buildStaticHtml({ indexHtml, readAsset, bundle }) {
  // 자산 글은 치환 함수로 넣는다 — 문자열로 넘기면 글 안의 `$&`·`$1` 이 치환 패턴으로 읽힌다.
  const scripts = [];
  const styles = [];
  let template = indexHtml.replace(MODULE_SCRIPT, (_, src) => {
    scripts.push(src);
    return `\u0000script${scripts.length - 1}\u0000`;
  });
  template = template.replace(STYLESHEET, (_, href) => {
    styles.push(href);
    return `\u0000style${styles.length - 1}\u0000`;
  });
  if (scripts.length === 0) throw new Error("dist/index.html 에 모듈 스크립트가 없다");
  const leftover = EXTERNAL_REFERENCE.exec(template);
  if (leftover !== null) {
    throw new Error(`문서 안에 넣지 못한 외부 참조가 남았다(청크가 갈라진 빌드인가): ${leftover[0].trim()}`);
  }
  const data =
    `<script type="application/json" id="${STATIC_BUNDLE_ELEMENT_ID}">` +
    `${escapeJsonForHtml(JSON.stringify(bundle))}</script>\n    `;
  return template.replace(/\u0000(script|style)(\d+)\u0000/g, (_, kind, index) => {
    if (kind === "style") return `<style>${readAsset(styles[Number(index)])}</style>`;
    const script = `<script type="module">${escapeScriptForHtml(readAsset(scripts[Number(index)]))}</script>`;
    return index === "0" ? `${data}${script}` : script;
  });
}
