// 이 사례들은 DESIGN.md 의 채팅 표기 절과 같아야 한다 — 표기 규칙을 바꾸면 그 절과 이 표를 함께 고친다.
// 대화 목록의 한 줄 미리보기는 메시지 본문에 보이는 글자와 어긋나면 안 되므로, 렌더러가 화면에 남기는
// 글자(textContent)와 같은지를 함께 확인한다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import { describe, expect, it } from "vitest";

import { CHAT_MARKDOWN_OPTIONS, prepareChatMarkdownSource } from "./chatMarkdown";
import { stripChatNotation } from "./stripChatNotation";

function renderedText(content: string): string {
  const html = renderToStaticMarkup(
    createElement(Markdown, CHAT_MARKDOWN_OPTIONS, prepareChatMarkdownSource(content)),
  );
  // 블록 경계와 줄바꿈은 한 칸 띄움이 되고, 인라인 요소(em·strong·code)의 경계는 글자를 띄우지 않는다.
  return html
    .replace(/<\/?(em|strong|code)>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

describe("stripChatNotation", () => {
  it.each([
    ['*둘러본다* "누구 있어요?"', '둘러본다 "누구 있어요?"'],
    ['*조심스럽게 주위를 둘러본다* "누구 있어요?" (조금 무섭다)', '조심스럽게 주위를 둘러본다 "누구 있어요?" (조금 무섭다)'],
    ['그녀가 웃었다*"안녕"*', '그녀가 웃었다"안녕"'],
    ["*계단을 내려온다", "계단을 내려온다"],
    ["*첫 문단\n\n둘째 문단", "첫 문단 둘째 문단"],
    ["**강조**", "강조"],
    ["***", ""],
    ["텍스트\n---", "텍스트"],
    ["`a*b`", "a*b"],
    ["```js\n상태 *값*\n```\n다음", "상태 *값* 다음"],
    ["\\*별표\\*", "*별표*"],
    ["* 목록", "목록"],
    ["- 대사", "대사"],
    ["1. 첫째\n2. 둘째", "첫째 둘째"],
    ["2026. 9. 29. 오늘", "2026. 9. 29. 오늘"],
    ["> D+0 | 13:00 | 장소\n\n*문을 연다*", "D+0 | 13:00 | 장소 문을 연다"],
    [">_< 싫어", ">_< 싫어"],
    ["_밑줄_", "_밑줄_"],
    ["# 제목", "# 제목"],
    ["[링크](x)", "[링크](x)"],
    ["<b>굵게</b>", "<b>굵게</b>"],
    ["반가워~ 또 봐~", "반가워~ 또 봐~"],
    ["별점 5* 줬다", "별점 5* 줬다"],
    ["첫 줄\n둘째 줄", "첫 줄 둘째 줄"],
    ["**굵게*", "굵게"],
    // 렌더러처럼 문단 단위로 짝짓는다(줄 단위가 아니다).
    ['*그녀는 창밖을 본다.\n비가 내린다.* "춥다."', '그녀는 창밖을 본다. 비가 내린다. "춥다."'],
    ["*웃는다 *걷는다*", "웃는다 걷는다"],
    ["**굵게* 다음", "굵게 다음"],
    ['그는 **"안 돼!"**라고 외쳤다', '그는 "안 돼!"라고 외쳤다'],
    ["> 2026. 9. 29. | 23:40 | 옥상", "2026. 9. 29. | 23:40 | 옥상"],
    ["> >_< 싫어", ">_< 싫어"],
  ])("%j -> %j", (input, expected) => {
    expect(stripChatNotation(input)).toBe(expected);
  });

  // 렌더러와 문자열 처리가 서로 다른 규칙을 갖게 되면 여기서 드러난다.
  it.each([
    '*둘러본다* "누구 있어요?"',
    '*조심스럽게 주위를 둘러본다* "누구 있어요?" (조금 무섭다)',
    '그녀가 웃었다*"안녕"*',
    '*"안녕"*이라고 말했다',
    "*웃는다.*안녕",
    "*계단을 내려온다",
    "*첫 문단\n\n둘째 문단",
    "첫 *문단 끝*\n둘째 줄 *열림",
    "**강조**",
    "***",
    "텍스트\n---",
    "`a*b`",
    "```\n상태 *값*\n```",
    "\\*별표\\*",
    "*별표\\*를 본다",
    "* 목록",
    "* 목록 *강조*",
    "1. 첫째\n2. 둘째",
    "반가워~ 또 봐~",
    "# 제목",
    "[링크](x)",
    "<b>굵게</b>",
    "| a | b |\n|---|---|\n| 1 | 2 |",
    "> D+0 | 13:00 | 장소",
    "*말머리를 세우며",
    "첫 줄\n둘째 줄",
    "2026. 9. 29. 오늘",
    "9. 29. 저녁",
    "_밑줄_",
    ">_< 싫어",
    "**굵게*",
    "**굵게* 다음",
    "**굵",
    "***굵은 지문*",
    '그는 **"안 돼!"**라고 외쳤다',
    '*그가 **"안 돼"**라고 했다*',
    '다*"안녕" **"굵게"**라고*',
    '*그녀는 창밖을 본다.\n비가 내린다.* "춥다."',
    "*웃는다 *걷는다*",
    "> 2026. 9. 29. | 23:40 | 옥상",
    "- 2026. 9. 29. 일기",
    "> >_< 싫어",
    "*a\n\n*",
    "별점 5* \n\n다음 문단",
    "별점 5* ",
    "> 별점 5* ",
    '**"왜?"***고개를 든다*',
    '*고개를 든다***"왜?"**',
    "*a **b** c*",
    "*a*b*c*",
    "*웃는다 *",
    "별점 5* 줬다",
    "2*3=6 이고 4*5=20",
    "안녕 *",
    "*",
  ])("matches the rendered text for %j", (input) => {
    expect(stripChatNotation(input)).toBe(renderedText(input));
  });

  it("handles tens of thousands of characters without overflowing the stack", () => {
    for (const input of ["*a ".repeat(20000), "> ".repeat(20000) + "a", "- ".repeat(20000) + "a"]) {
      const started = performance.now();
      expect(() => stripChatNotation(input)).not.toThrow();
      expect(performance.now() - started).toBeLessThan(2000);
    }
    expect(stripChatNotation("*a ".repeat(2500))).toBe(renderedText("*a ".repeat(2500)));
  });
});
