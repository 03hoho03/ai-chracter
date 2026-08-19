import { describe, expect, it } from "vitest";

import { buildMetaTags } from "./meta";

describe("buildMetaTags", () => {
  it("상세 페이지 한 벌을 만든다", () => {
    const html = buildMetaTags({
      title: "미호 — 또나",
      description: "여우 캐릭터",
      canonical: "https://ddona.example/content/character/1",
      ogTitle: "미호",
      ogDescription: "여우 캐릭터",
      ogImage: "https://ddona.example/og/content/1.jpg",
      ogUrl: "https://ddona.example/content/character/1",
      ogType: "article",
      ogSiteName: "또나",
      twitterCard: "summary",
    });

    expect(html.split("\n")).toEqual([
      "<title>미호 — 또나</title>",
      '<meta name="description" content="여우 캐릭터" />',
      '<link rel="canonical" href="https://ddona.example/content/character/1" />',
      '<meta property="og:title" content="미호" />',
      '<meta property="og:description" content="여우 캐릭터" />',
      '<meta property="og:image" content="https://ddona.example/og/content/1.jpg" />',
      '<meta property="og:url" content="https://ddona.example/content/character/1" />',
      '<meta property="og:type" content="article" />',
      '<meta property="og:site_name" content="또나" />',
      '<meta name="twitter:card" content="summary" />',
    ]);
  });

  it("주어지지 않은 항목은 태그를 만들지 않는다", () => {
    const html = buildMetaTags({
      canonical: "https://ddona.example/",
      ogUrl: "https://ddona.example/",
    });

    expect(html).toBe(
      '<link rel="canonical" href="https://ddona.example/" />\n' +
        '<meta property="og:url" content="https://ddona.example/" />',
    );
  });

  it("빈 메타는 빈 문자열이다", () => {
    expect(buildMetaTags({})).toBe("");
  });

  it("빈 문자열은 undefined와 달리 태그가 된다 — 값을 비우고 싶다는 뜻이다", () => {
    expect(buildMetaTags({ ogDescription: "" })).toBe(
      '<meta property="og:description" content="" />',
    );
  });

  it("모든 값이 이스케이프를 통과한다 — 이름·소개는 사용자 입력이다", () => {
    const html = buildMetaTags({
      title: `"><script>alert(1)</script>`,
      description: `" onload="x`,
      ogTitle: "A & B",
      ogImage: "https://ddona.example/og/content/1.jpg?a=1&b=2",
    });

    expect(html).not.toContain("<script>");
    expect(html.split("\n")).toEqual([
      "<title>&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;</title>",
      '<meta name="description" content="&quot; onload=&quot;x" />',
      '<meta property="og:title" content="A &amp; B" />',
      '<meta property="og:image" content="https://ddona.example/og/content/1.jpg?a=1&amp;b=2" />',
    ]);
  });

  it("robots를 넣을 수 있다 — 프로필은 미리보기만 되고 색인은 막는다", () => {
    expect(buildMetaTags({ robots: "noindex" })).toBe(
      '<meta name="robots" content="noindex" />',
    );
  });
});
