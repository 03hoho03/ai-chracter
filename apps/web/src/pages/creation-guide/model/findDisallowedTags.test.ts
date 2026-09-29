import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import { describe, expect, it } from "vitest";

import { GUIDE_MARKDOWN_OPTIONS } from "../config/guideMarkdownOptions";
import { findDisallowedTags } from "./findDisallowedTags";

describe("rendered-tag check", () => {
  it("accepts the prose vocabulary the guide renders", () => {
    const source = [
      "문단과 **굵게**, `*지문*` 인라인 코드, [링크](/guide/character).",
      "",
      "### 소제목",
      "",
      "- **칸 이름**: 설명",
      "1. 순서",
      "",
      "> 덧붙이는 말",
      "",
      "---",
      "줄 끝 역슬래시\\",
      "다음 줄",
    ].join("\n");
    expect(findDisallowedTags(source)).toEqual([]);
  });

  it.each([
    ["single-star emphasis", "*기울임*", "em"],
    ["underscore emphasis", "이건 _강조_ 이고", "em"],
    ["triple-star emphasis", "***셋***", "em"],
    ["an h1", "# 제목", "h1"],
    ["an h2 without an id", "## 제목", "h2"],
    ["a setext heading", "텍스트\n---", "h2"],
    ["an h4", "#### 제목", "h4"],
    ["a three-backtick fence", "```\n코드\n```", "pre"],
    ["an indented code block", "    코드", "pre"],
    ["an image", "![그림](a.png)", "img"],
  ])("rejects %s", (_label, source, tag) => {
    expect(findDisallowedTags(source)).toContain(tag);
  });

  // GFM 이 없으니 물결표 범위에 취소선이 그어지지 않는다(`del` 이 생기지 않는다).
  it("keeps tilde ranges as plain text", () => {
    const source = "판정은 10~15턴 사이, 엔딩은 20~25턴";
    expect(findDisallowedTags(source)).toEqual([]);
    expect(renderToStaticMarkup(createElement(Markdown, { ...GUIDE_MARKDOWN_OPTIONS, children: source }))).toContain(
      source,
    );
  });

  // 검사를 빠져나간 구문이 있어도 렌더러가 글자까지 지우지 않는다(요소만 벗긴다).
  it("unwraps disallowed elements in the renderer instead of dropping their text", () => {
    const html = renderToStaticMarkup(
      createElement(Markdown, { ...GUIDE_MARKDOWN_OPTIONS, children: "이건 _강조_ 이고" }),
    );
    expect(html).toBe("<p>이건 강조 이고</p>");
  });

  it("drops raw HTML such as comments instead of printing it", () => {
    const html = renderToStaticMarkup(
      createElement(Markdown, { ...GUIDE_MARKDOWN_OPTIONS, children: "앞 <!-- 메모 --> 뒤" }),
    );
    expect(html).not.toContain("메모");
  });
});
