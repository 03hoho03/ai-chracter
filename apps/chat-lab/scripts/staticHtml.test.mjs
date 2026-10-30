import { describe, expect, it } from "vitest";

import { parseStaticBundle } from "../src/shared/api/staticBundle.ts";
import { STATIC_BUNDLE_ELEMENT_ID } from "../src/shared/api/staticBundleElement.ts";

import { buildStaticHtml, escapeJsonForHtml, escapeScriptForHtml } from "./staticHtml.mjs";

// Vite 가 `dist/index.html` 에 쓰는 꼴 — 모듈 스크립트 하나, 스타일시트 하나, 문서 안 SVG 아이콘, 첫 그림 전 테마 스크립트.
const INDEX_HTML = `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <title>chat-lab</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3C/svg%3E" />
    <script>
      try {
        var theme = window.localStorage.getItem("chat-lab:theme");
      } catch (error) {}
    </script>
    <script type="module" crossorigin src="/assets/index-abc123.js"></script>
    <link rel="stylesheet" crossorigin href="/assets/index-def456.css">
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
`;

// 문자열 안에 HTML 파서가 스크립트를 끊거나(`</script`, 대소문자 무관) 끊지 못하게 만드는(`<!--`) 글을 담은 앱 코드.
const PROBE = ["</script>", "<!--", "</SCRIPT >", "<script>", "a < b"];
const APP_JS = `var probe = ${JSON.stringify(PROBE)};\nvar tag = \`</Script>\`;\n`;
const APP_CSS = ":root{color-scheme:light dark}body{margin:0}";

const ASSETS = { "/assets/index-abc123.js": APP_JS, "/assets/index-def456.css": APP_CSS };

function readAsset(href) {
  const content = ASSETS[href];
  if (content === undefined) throw new Error(`없는 자산: ${href}`);
  return content;
}

const BUNDLE = {
  raw: false,
  detail: { run: { runId: "cnVucy9hL2NoYXQuanNvbmw" }, turns: [] },
  metrics: { turns: [] },
  turns: [
    {
      turn: 1,
      attempts: [{ record: { userText: "</script><!--<script>", reply: "</SCRIPT >는 a < b 처럼" } }],
    },
  ],
};

/**
 * 그 요소의 글로 브라우저가 읽는 범위 — 여는 태그 뒤부터 대소문자를 가리지 않는 첫 `</script` 앞까지. 글 안에 `<!--` 가 없을
 * 때만 HTML 파서의 규칙과 같아서, 부르는 테스트가 `<!--` 가 없는지도 함께 본다.
 */
function scriptBody(html, openTagPattern) {
  const open = openTagPattern.exec(html);
  if (open === null) throw new Error(`여는 태그가 없다: ${openTagPattern}`);
  const start = open.index + open[0].length;
  const end = html.slice(start).search(/<\/script/i);
  if (end < 0) throw new Error("닫는 태그가 없다");
  return html.slice(start, start + end);
}

const DATA_TAG = new RegExp(`<script\\b[^>]*\\bid="${STATIC_BUNDLE_ELEMENT_ID}"[^>]*>`);
const MODULE_TAG = /<script\b[^>]*\btype="module"[^>]*>/;

function build() {
  return buildStaticHtml({ indexHtml: INDEX_HTML, readAsset, bundle: BUNDLE });
}

describe("escapeJsonForHtml", () => {
  it("스크립트를 끊거나 주석으로 여는 글이 들어 있어도, 이스케이프한 글을 다시 읽으면 원래 값과 같다", () => {
    const value = { a: "</script>", b: "<!--", c: "</SCRIPT", d: "<", e: "한글   줄" };
    const escaped = escapeJsonForHtml(JSON.stringify(value));

    expect(JSON.parse(escaped)).toEqual(value);
  });

  it("이스케이프한 글에는 `<` 가 하나도 남지 않는다", () => {
    expect(escapeJsonForHtml(JSON.stringify({ a: "</script><!--<b>", b: "<<" }))).not.toContain("<");
  });
});

describe("escapeScriptForHtml", () => {
  it("코드 안의 `</script`(대소문자 무관)와 `<!--` 가 남지 않는다", () => {
    const escaped = escapeScriptForHtml(APP_JS);

    expect(escaped).not.toMatch(/<\/script/i);
    expect(escaped).not.toContain("<!--");
  });

  it("이스케이프한 코드를 돌리면 원래 코드와 같은 값이 나온다(문자열·템플릿 글 모두)", () => {
    const escaped = escapeScriptForHtml(APP_JS);
    const run = (code) => new Function(`${code}\nreturn [probe, tag];`)();

    expect(run(escaped)).toEqual(run(APP_JS));
    expect(run(escaped)).toEqual([PROBE, "</Script>"]);
  });
});

describe("buildStaticHtml", () => {
  it("모듈 스크립트·스타일시트를 문서 안에 넣어 외부 참조가 하나도 없다", () => {
    const html = build();

    expect(html).not.toMatch(/\ssrc\s*=/i);
    const hrefs = [...html.matchAll(/\shref\s*=\s*["']?([^"'\s>]*)/gi)].map((match) => match[1]);
    expect(hrefs.every((href) => href.startsWith("data:"))).toBe(true);
    expect(html).toContain(APP_CSS);
    // 모듈이 아닌 첫 그림 전 스크립트는 그대로 남는다.
    expect(html).toContain('window.localStorage.getItem("chat-lab:theme")');
  });

  it("넣은 앱 코드 안의 `</script` 가 문서를 끊지 않는다 — 브라우저가 읽는 글을 돌리면 원래 코드와 같은 값이 나온다", () => {
    const body = scriptBody(build(), MODULE_TAG);

    expect(body).not.toContain("<!--");
    expect(new Function(`${body}\nreturn [probe, tag];`)()).toEqual([PROBE, "</Script>"]);
  });

  it("주입 데이터 태그가 앱 스크립트보다 먼저 온다", () => {
    const html = build();
    const data = DATA_TAG.exec(html);
    const app = MODULE_TAG.exec(html);

    expect(data).not.toBeNull();
    expect(app).not.toBeNull();
    expect(data.index).toBeLessThan(app.index);
    expect(data[0]).toContain('type="application/json"');
  });

  it("주입 데이터를 앱이 읽는 그대로 되돌리면 원래 묶음과 같다", () => {
    const body = scriptBody(build(), DATA_TAG);

    expect(body).not.toContain("<");
    expect(parseStaticBundle(body)).toEqual({ kind: "ready", bundle: BUNDLE });
  });

  it("넣지 못한 외부 참조가 남으면 던진다 — 청크가 갈라진 빌드를 반쯤 빈 파일로 내보내지 않는다", () => {
    const split = INDEX_HTML.replace(
      "</head>",
      '  <link rel="modulepreload" crossorigin href="/assets/vendor-111.js">\n  </head>',
    );

    expect(() =>
      buildStaticHtml({
        indexHtml: split,
        readAsset: (href) => (href === "/assets/vendor-111.js" ? "export {}" : readAsset(href)),
        bundle: BUNDLE,
      }),
    ).toThrow();
  });
});
