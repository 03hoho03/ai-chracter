import { describe, expect, it } from "vitest";

import { buildJsonLd, escapeHtml, injectHead } from "./html";

/** apps/web/index.html의 head 구조를 최소로 옮긴 픽스처(US-009 이후 형태). */
const INDEX_HTML = `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>또나 — AI 캐릭터 챗</title>
    <meta name="description" content="홈 설명" />
    <meta property="og:title" content="또나" />
    <meta property="og:image" content="https://ddona.example/og-default.png" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <script>
      if (localStorage.getItem("theme") !== "light") {
        document.documentElement.classList.add("dark");
      }
    </script>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
`;

describe("escapeHtml", () => {
  it("속성 탈출 시도(따옴표 + 태그 열기)를 무력화한다", () => {
    const escaped = escapeHtml(`"><script>alert(1)</script>`);

    expect(escaped).toBe("&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(escaped).not.toContain("<");
    expect(escaped).not.toContain('"');
  });

  it("따옴표를 닫고 이벤트 핸들러를 붙이는 시도를 막는다", () => {
    expect(escapeHtml(`" onload="x`)).toBe("&quot; onload=&quot;x");
  });

  it("작은따옴표도 이스케이프한다 — 속성을 작은따옴표로 감싼 태그가 섞여도 안전해야 한다", () => {
    expect(escapeHtml("' onerror='x")).toBe("&#39; onerror=&#39;x");
  });

  it("앰퍼샌드를 먼저 바꿔 다른 엔티티를 이중 이스케이프하지 않는다", () => {
    expect(escapeHtml("A & B")).toBe("A &amp; B");
    // `<`가 `&amp;lt;`가 되면 안 된다 — & 치환이 나중이면 그렇게 된다.
    expect(escapeHtml("<b>")).toBe("&lt;b&gt;");
    // 반대로 이미 이스케이프된 문자열을 다시 넣으면 이중 이스케이프된다(=한 번만 적용할 것).
    expect(escapeHtml("&amp;")).toBe("&amp;amp;");
  });

  it("이스케이프할 문자가 없으면 그대로 둔다", () => {
    expect(escapeHtml("또나 캐릭터 챗")).toBe("또나 캐릭터 챗");
  });
});

describe("buildJsonLd", () => {
  it("문자열 안의 </script>를 무력화하고도 값은 그대로 읽힌다", () => {
    const name = `</script><script>alert(1)</script>`;

    const html = buildJsonLd({ "@type": "CreativeWork", name });

    const body = html.slice(
      html.indexOf(">") + 1,
      html.lastIndexOf("</script>"),
    );
    expect(body).not.toContain("<");
    expect(JSON.parse(body)).toEqual({ "@type": "CreativeWork", name });
  });

  it("script 태그로 감싼다", () => {
    expect(buildJsonLd({ a: 1 })).toBe(
      '<script type="application/ld+json">{"a":1}</script>',
    );
  });
});

describe("injectHead", () => {
  it("</head> 앞에 메타를 넣는다", () => {
    const result = injectHead(
      INDEX_HTML,
      '<meta property="og:url" content="https://ddona.example/" />',
    );

    expect(result).toContain(
      '<meta property="og:url" content="https://ddona.example/" />',
    );
    expect(result.indexOf("og:url")).toBeLessThan(result.indexOf("</head>"));
  });

  it("같은 키의 기존 태그를 지우고 주입한 것만 남긴다", () => {
    const result = injectHead(
      INDEX_HTML,
      `<title>미호 — 또나</title>\n<meta property="og:title" content="미호" />`,
    );

    expect(result.match(/<title>/g)).toHaveLength(1);
    expect(result).toContain("<title>미호 — 또나</title>");
    expect(result).not.toContain("또나 — AI 캐릭터 챗");
    expect(result.match(/property="og:title"/g)).toHaveLength(1);
    expect(result).toContain('<meta property="og:title" content="미호" />');
  });

  it("주입하지 않은 태그는 건드리지 않는다", () => {
    const result = injectHead(
      INDEX_HTML,
      '<link rel="canonical" href="https://ddona.example/" />',
    );

    expect(result).toContain('<meta charset="UTF-8" />');
    expect(result).toContain('<meta name="viewport"');
    expect(result).toContain(
      '<link rel="icon" href="/favicon.svg" type="image/svg+xml" />',
    );
    expect(result).toContain(
      '<meta property="og:image" content="https://ddona.example/og-default.png" />',
    );
    expect(result).toContain("<title>또나 — AI 캐릭터 챗</title>");
    expect(result).toContain("localStorage.getItem");
  });

  it("canonical은 rel로 식별해 중복시키지 않는다", () => {
    const once = injectHead(
      INDEX_HTML,
      '<link rel="canonical" href="https://ddona.example/" />',
    );
    const twice = injectHead(
      once,
      '<link rel="canonical" href="https://ddona.example/x" />',
    );

    expect(twice.match(/rel="canonical"/g)).toHaveLength(1);
    expect(twice).toContain('href="https://ddona.example/x"');
  });

  it("메타에 $& 같은 치환 시퀀스가 있어도 문자 그대로 남는다", () => {
    const result = injectHead(
      INDEX_HTML,
      '<meta property="og:description" content="$&$1$`" />',
    );

    expect(result).toContain('content="$&$1$`"');
  });

  it("</head>가 없으면 원본을 그대로 돌려준다", () => {
    const html = "<html><body>no head</body></html>";

    expect(injectHead(html, "<title>x</title>")).toBe(html);
  });
});
