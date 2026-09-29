// 이 사례들은 DESIGN.md 의 채팅 표기 절과 같아야 한다 — 표기 규칙을 바꾸면 그 절과 이 표를 함께 고친다.
// 원문 규칙은 `*…*` 가 지문(em), 그 밖이 대사이고, 허용하지 않는 마크다운 구문(제목·링크·이미지·HTML·표)은
// 요소를 만들지 않고 원문 글자 그대로 보여야 한다. 여기서는 컴포넌트의 스타일 없이 파이프라인이 만드는
// 구조만 본다(클래스는 컴포넌트 테스트가 본다).
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import { describe, expect, it } from "vitest";

import { CHAT_MARKDOWN_OPTIONS, prepareChatMarkdownSource } from "./chatMarkdown";

function render(content: string): string {
  const html = renderToStaticMarkup(createElement(Markdown, CHAT_MARKDOWN_OPTIONS, prepareChatMarkdownSource(content)));
  // 블록 사이·줄바꿈 뒤에 react-markdown 이 넣는 개행은 구조와 무관하므로 걷어 낸다.
  return html.replace(/>\n</g, "><").replace(/<br\/>\n/g, "<br/>");
}

const Q = "&quot;";

describe("chat markdown pipeline", () => {
  describe("narration (em) and dialogue", () => {
    it.each([
      ['*둘러본다* "누구 있어요?"', `<p><em>둘러본다</em> ${Q}누구 있어요?${Q}</p>`],
      [
        '*조심스럽게 주위를 둘러본다* "누구 있어요?" (조금 무섭다)',
        `<p><em>조심스럽게 주위를 둘러본다</em> ${Q}누구 있어요?${Q} (조금 무섭다)</p>`,
      ],
      ["*둘러본다*는 듯이", "<p><em>둘러본다</em>는 듯이</p>"],
      ['"안녕."*손을 흔든다*', `<p>${Q}안녕.${Q}<em>손을 흔든다</em></p>`],
      ["*a **b** c*", "<p><em>a <strong>b</strong> c</em></p>"],
      ["*a*b*c*", "<p><em>a</em>b<em>c</em></p>"],
      ["*웃는다* *걷는다*", "<p><em>웃는다</em> <em>걷는다</em></p>"],
      ['"안녕" *웃는다*"잘가"', `<p>${Q}안녕${Q} <em>웃는다</em>${Q}잘가${Q}</p>`],
      ["「*웃는다*」", "<p>「<em>웃는다</em>」</p>"],
      ["*첫 줄\n둘째 줄*", "<p><em>첫 줄<br/>둘째 줄</em></p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  // 한국어는 글자와 구두점이 붙어 CommonMark 의 flanking 규칙이 `*` 를 강조로 못 쓴다.
  // 파서가 짝짓지 못한 별표를 공백 조건만으로 다시 짝지어 지문으로 만든다.
  describe("Korean flanking rescue", () => {
    it.each([
      ['그녀가 웃었다*"안녕"*', `<p>그녀가 웃었다<em>${Q}안녕${Q}</em></p>`],
      ['그녀가 웃었다 *"안녕"*', `<p>그녀가 웃었다 <em>${Q}안녕${Q}</em></p>`],
      ['*"안녕"*이라고 말했다', `<p><em>${Q}안녕${Q}</em>이라고 말했다</p>`],
      ["*웃는다.*안녕", "<p><em>웃는다.</em>안녕</p>"],
      ['*웃는다.*"안녕"', `<p><em>웃는다.</em>${Q}안녕${Q}</p>`],
      ['*웃는다*"안녕"', `<p><em>웃는다</em>${Q}안녕${Q}</p>`],
      ['"안녕"*웃는다*', `<p>${Q}안녕${Q}<em>웃는다</em></p>`],
      ["안녕*웃는다*", "<p>안녕<em>웃는다</em></p>"],
      ["*웃는다~*그래", "<p><em>웃는다~</em>그래</p>"],
      ["*웃는다…*그래", "<p><em>웃는다…</em>그래</p>"],
      ["*웃는다*…그래", "<p><em>웃는다</em>…그래</p>"],
      ["*「안녕」*이라고", "<p><em>「안녕」</em>이라고</p>"],
      ["*(웃음)*다음", "<p><em>(웃음)</em>다음</p>"],
      ['*"안녕" **굵게** 끝*다', `<p><em>${Q}안녕${Q} <strong>굵게</strong> 끝</em>다</p>`],
      // 닫는 별표 앞이 공백이어도 문단 끝이면 닫는다 — 뒤에 아무것도 없는 별표는 보여 줄 이유가 없다.
      ["*웃는다 *", "<p><em>웃는다 </em></p>"],
      // 앞뒤가 공백인 별표는 표기가 아니라 글자다.
      ["별점 5* 줬다", "<p>별점 5* 줬다</p>"],
      ["별점 5* 줬고 3* 받음", "<p>별점 5* 줬고 3* 받음</p>"],
      // 글자 사이 별표는 지문으로 읽힌다 — 알고 받아들인 오탐이다.
      ["2*3=6 이고 4*5=20", "<p>2<em>3=6 이고 4</em>5=20</p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  // 스트리밍 중과 저장 후가 같은 모양이어야 하므로, 닫히지 않은 여는 별표는 문단 끝까지 지문이다.
  describe("unclosed star auto-closes at paragraph end", () => {
    it.each([
      ["*계단을 내려온다", "<p><em>계단을 내려온다</em></p>"],
      ["*첫 문단\n\n둘째 문단", "<p><em>첫 문단</em></p><p>둘째 문단</p>"],
      ["첫 *문단 끝*\n둘째 줄 *열림", "<p>첫 <em>문단 끝</em><br/>둘째 줄 <em>열림</em></p>"],
      ["*말머리를 세우며", "<p><em>말머리를 세우며</em></p>"],
      ["*말머리를 세우며.", "<p><em>말머리를 세우며.</em></p>"],
      ["*말머리를 세우며 ", "<p><em>말머리를 세우며</em></p>"],
      ['*웃으며 "안녕"', `<p><em>웃으며 ${Q}안녕${Q}</em></p>`],
      ["*웃으며 (작게)", "<p><em>웃으며 (작게)</em></p>"],
      ["*abc\\", "<p><em>abc\\</em></p>"],
      ['그녀가 웃었다*"안녕', `<p>그녀가 웃었다<em>${Q}안녕</em></p>`],
      ["*a *b* c", "<p><em>a <em>b</em> c</em></p>"],
      ["*걷다가 **멈춘다** 그리고", "<p><em>걷다가 <strong>멈춘다</strong> 그리고</em></p>"],
      ["* 목록 *강조", "<ul><li>목록 <em>강조</em></li></ul>"],
      ["첫 줄\n* 목록 *열림", "<p>첫 줄</p><ul><li>목록 <em>열림</em></li></ul>"],
      ["`a*b` *열림", "<p><code>a*b</code> <em>열림</em></p>"],
      ["```\n*코드\n\n더\n```\n*열림", "<pre><code>*코드\n\n더\n</code></pre><p><em>열림</em></p>"],
      // 뒤 내용이 없는 여는 별표는 지운다(앞 공백은 남지만 보이지 않는다).
      ["안녕 *", "<p>안녕 </p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  // 굵게 표지도 한국어 글자·구두점에 붙으면 파서가 짝짓지 못한다. 단독 별표와 같은 공백 조건으로 다시 짝짓는다.
  describe("Korean flanking rescue for strong", () => {
    it.each([
      ['그는 **"안 돼!"**라고 외쳤다', `<p>그는 <strong>${Q}안 돼!${Q}</strong>라고 외쳤다</p>`],
      ['**"대사"**라고', `<p><strong>${Q}대사${Q}</strong>라고</p>`],
      ['*그가 **"안 돼"**라고 했다*', `<p><em>그가 <strong>${Q}안 돼${Q}</strong>라고 했다</em></p>`],
      // 다시 짝지어 만든 지문 안의 굵게도 짝지어야 한다.
      ['다*"안녕" **"굵게"**라고*', `<p>다<em>${Q}안녕${Q} <strong>${Q}굵게${Q}</strong>라고</em></p>`],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  // 닫히지 않은 굵게도 문단 끝까지 굵게다 — 스트리밍 중 날것의 `**` 가 보이다가, 닫는 별표가 하나만
  // 도착한 순간 지문으로 뒤집혔다가, 다 도착하면 굵게로 돌아오는 깜빡임을 없앤다.
  describe("unclosed strong auto-closes and never flips while streaming", () => {
    it.each([
      [["**정말 중요해", "**정말 중요해*", "**정말 중요해**"], "<p><strong>정말 중요해</strong></p>"],
      [["**굵게*", "**굵게**"], "<p><strong>굵게</strong></p>"],
      [['**"대사"', '**"대사"*', '**"대사"**'], `<p><strong>${Q}대사${Q}</strong></p>`],
      [["**굵게* 다음", "**굵게** 다음"], "<p><strong>굵게</strong> 다음</p>"],
      [
        ["***굵은 지문", "***굵은 지문*", "***굵은 지문**", "***굵은 지문***"],
        "<p><em><strong>굵은 지문</strong></em></p>",
      ],
    ])("%j", (inputs, expected) => {
      for (const input of inputs) expect(render(input)).toBe(expected);
    });

    it("renders an unclosed '**' at the very start as strong", () => {
      expect(render("**굵")).toBe("<p><strong>굵</strong></p>");
    });
  });

  describe("allowed elements", () => {
    it.each([
      ["**강조**", "<p><strong>강조</strong></p>"],
      ["***", "<hr/>"],
      ["---", "<hr/>"],
      ["텍스트\n---", "<p>텍스트</p><hr/>"],
      ["대사\n---\n다음", "<p>대사</p><hr/><p>다음</p>"],
      ["`a*b`", "<p><code>a*b</code></p>"],
      ["```\n상태 *값*\n```", "<pre><code>상태 *값*\n</code></pre>"],
      ["* 목록", "<ul><li>목록</li></ul>"],
      ["* 목록 *강조*", "<ul><li>목록 <em>강조</em></li></ul>"],
      ["- 대사", "<ul><li>대사</li></ul>"],
      ["1. 첫째", "<ol><li>첫째</li></ol>"],
      ["1. 첫째\n2. 둘째", "<ol><li>첫째</li><li>둘째</li></ol>"],
      ["> D+0 | 13:00 | 장소", "<blockquote><p>D+0 | 13:00 | 장소</p></blockquote>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  describe("escapes", () => {
    it.each([
      ["\\*별표\\*", "<p>*별표*</p>"],
      ["\\*별표\\* *열림", "<p>*별표* <em>열림</em></p>"],
      // 새로 만든 지문 안으로 들어간 이스케이프 별표도 글자로 돌아와야 한다.
      ["*별표\\*를 본다", "<p><em>별표*를 본다</em></p>"],
      ["`\\*`", "<p><code>\\*</code></p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  // 채팅에서 만들지 않는 요소는 원문이 사라지지 않고 글자로 남아야 한다.
  describe("disallowed syntax stays as literal text", () => {
    it.each([
      ["# 제목", "<p># 제목</p>"],
      ["#태그 없음", "<p>#태그 없음</p>"],
      ["텍스트\n===", "<p>텍스트<br/>===</p>"],
      ["[링크](https://x.com)", "<p>[링크](https://x.com)</p>"],
      ["![img](a.png)", "<p>![img](a.png)</p>"],
      ["https://x.com", "<p>https://x.com</p>"],
      ["<https://x.com>", "<p>&lt;https://x.com&gt;</p>"],
      ["[1]: https://x.com", "<p>[1]: https://x.com</p>"],
      ["<b>굵게</b>", "<p>&lt;b&gt;굵게&lt;/b&gt;</p>"],
      ["<div>블록</div>", "<p>&lt;div&gt;블록&lt;/div&gt;</p>"],
      ["| a | b |\n|---|---|\n| 1 | 2 |", "<p>| a | b |<br/>|---|---|<br/>| 1 | 2 |</p>"],
      ["    들여쓴 줄", "<p>들여쓴 줄</p>"],
      ["첫 줄\n    들여쓴 둘째 줄", "<p>첫 줄<br/>들여쓴 둘째 줄</p>"],
      ["&lt;태그&gt; &amp;", "<p>&lt;태그&gt; &amp;</p>"],
      // GFM 을 쓰지 않으므로 물결표는 취소선이 되지 않는다.
      ["반가워~ 또 봐~", "<p>반가워~ 또 봐~</p>"],
      ["~~취소~~", "<p>~~취소~~</p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  // 밑줄 강조는 이모티콘(`>_<`, `^_^`)을 깨뜨리므로 쓰지 않는다.
  describe("underscore emphasis is shown as typed", () => {
    it.each([
      ["_밑줄_", "<p>_밑줄_</p>"],
      ["__밑줄__", "<p>__밑줄__</p>"],
      ["_*웃음*_", "<p>_<em>웃음</em>_</p>"],
      ["^_^ 좋아 ^_^", "<p>^_^ 좋아 ^_^</p>"],
      ["ㅠ_ㅠ 슬퍼", "<p>ㅠ_ㅠ 슬퍼</p>"],
      ["file_name_here", "<p>file_name_here</p>"],
      ["-_- 뭐야", "<p>-_- 뭐야</p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  describe("line-start ambiguity", () => {
    it.each([
      // 줄 머리 `>` 뒤에 공백이 없으면 인용이 아니라 이모티콘이다.
      [">_< 싫어", "<p>&gt;_&lt; 싫어</p>"],
      [">_< 싫어 >_<", "<p>&gt;_&lt; 싫어 &gt;_&lt;</p>"],
      // 날짜형 번호는 목록이 아니다.
      ["2026. 9. 29. 오늘", "<p>2026. 9. 29. 오늘</p>"],
      ["9. 29. 저녁", "<p>9. 29. 저녁</p>"],
      ["3. 규칙은 이렇다", '<ol start="3"><li>규칙은 이렇다</li></ol>'],
      // 인용·목록 안에서도 같다 — 컨테이너 표지 뒤의 글자가 줄 머리다.
      ["> 2026. 9. 29. | 23:40 | 옥상", "<blockquote><p>2026. 9. 29. | 23:40 | 옥상</p></blockquote>"],
      ["- 2026. 9. 29. 일기", "<ul><li>2026. 9. 29. 일기</li></ul>"],
      ["> - 2026. 9. 29.", "<blockquote><ul><li>2026. 9. 29.</li></ul></blockquote>"],
      ["> >_< 싫어", "<blockquote><p>&gt;_&lt; 싫어</p></blockquote>"],
      // 코드 블록 안은 줄 머리 처리를 하지 않는다.
      ["```\n2026. 9. 29.\n>_<\n```", "<pre><code>2026. 9. 29.\n&gt;_&lt;\n</code></pre>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  describe("line breaks", () => {
    it.each([
      ["첫 줄\n둘째 줄", "<p>첫 줄<br/>둘째 줄</p>"],
      ["첫 줄\r\n둘째 줄", "<p>첫 줄<br/>둘째 줄</p>"],
      ["끝\\\n다음", "<p>끝<br/>다음</p>"],
      ["끝  \n다음", "<p>끝<br/>다음</p>"],
      ["첫 줄\n\n\n\n둘째 문단", "<p>첫 줄</p><p>둘째 문단</p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  // 공백이 뒤따르는 단독 별표는 여는 표지가 될 수 없어 글자로 남는다. 파서가 문단 끝 공백을 먼저
  // 잘라 내도 결과가 같아야 한다(미리보기와도 같아야 한다).
  describe("a lone star followed by trailing whitespace stays", () => {
    it.each([
      ["별점 5* \n\n다음 문단", "<p>별점 5*</p><p>다음 문단</p>"],
      ["별점 5* ", "<p>별점 5*</p>"],
      ["> 별점 5* ", "<blockquote><p>별점 5*</p></blockquote>"],
      // 공백 없이 끝나는 별표는 반쪽 표지라 지운다.
      ["별점 5*\n\n다음 문단", "<p>별점 5</p><p>다음 문단</p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });
  });

  it("closes bold with a longer run and lets the rest open narration", () => {
    expect(render('**"왜?"***고개를 든다*')).toBe(`<p><strong>${Q}왜?${Q}</strong><em>고개를 든다</em></p>`);
    expect(render('*고개를 든다***"왜?"**')).toBe(`<p><em>고개를 든다</em><strong>${Q}왜?${Q}</strong></p>`);
  });

  // 사용자 입력 길이에는 상한이 없다. 짝 없는 표지나 깊은 중첩이 몇만 자 이어져도 방이 깨지면 안 된다
  // (재귀가 입력 길이만큼 깊어지면 호출 스택이 넘친다).
  describe("pathological input", () => {
    const LIMIT_MS = 1000;
    it.each([
      ["unclosed openers x2500", "*a ".repeat(2500)],
      ["unclosed openers x20000", "*a ".repeat(20000)],
      ["unclosed strong openers x20000", "**a ".repeat(20000)],
      ["nested closed emphasis x10000", "*a ".repeat(10000) + "b*".repeat(10000)],
      ["nested quotes x20000", "> ".repeat(20000) + "a"],
      ["nested lists x20000", "- ".repeat(20000) + "a"],
      ["alternating markers x10000", "*a **b ".repeat(5000) + "c** d*".repeat(5000)],
    ])("%s renders quickly without overflowing the stack", (_name, input) => {
      const started = performance.now();
      const html = render(input);
      const elapsed = performance.now() - started;
      expect(html.length).toBeGreaterThan(0);
      expect(elapsed).toBeLessThan(LIMIT_MS);
    });

    it("keeps every word of an unclosed-opener flood", () => {
      const html = render("*a ".repeat(2500));
      expect(html.match(/a/g)?.length).toBe(2500);
    });

    it("survives random mixes of notation characters", () => {
      // 시드 고정 난수 — 실패하면 같은 입력을 다시 만들 수 있다.
      let seed = 42;
      const random = () => {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        return seed / 2147483648;
      };
      const alphabet = ["*", "*", "*", "a", "가", " ", "\n", '"', ">", "- ", "_", "`", "\\", "1. "];
      for (let round = 0; round < 50; round += 1) {
        const input = Array.from({ length: 4000 }, () => alphabet[Math.floor(random() * alphabet.length)]).join("");
        expect(() => render(input)).not.toThrow();
      }
    });
  });

  // 끝의 단독 `*` 줄은 빈 목록을 만든다. 스트리밍 중이든 저장 후든 보여 줄 것이 없으니 지운다.
  describe("trailing lone star line", () => {
    it.each([
      ["*", ""],
      ["* ", ""],
      ["*\n", ""],
      ["안녕\n\n*", "<p>안녕</p>"],
      ["*a\n\n*", "<p><em>a</em></p>"],
      ["*a\n\n*\n", "<p><em>a</em></p>"],
    ])("%j", (input, expected) => {
      expect(render(input)).toBe(expected);
    });

    it("keeps a trailing star inside an open code fence", () => {
      expect(render("```\n*")).toBe("<pre><code>*\n</code></pre>");
    });
  });
});
