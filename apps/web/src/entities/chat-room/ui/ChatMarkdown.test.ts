// 이 사례들은 DESIGN.md 의 채팅 표기 절과 같아야 한다 — 표기 규칙을 바꾸면 그 절과 이 표를 함께 고친다.
// 구조는 모델 테스트가 보고, 여기서는 표기마다 입히는 스타일 계약만 본다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatMarkdown } from "./ChatMarkdown";

type RenderOptions = { codeBlockSurface?: "muted" | "secondary" };

function render(content: string, options: RenderOptions = {}): string {
  return renderToStaticMarkup(createElement(ChatMarkdown, { content, ...options }));
}

function classOf(html: string, tag: string): string {
  const match = new RegExp(`<${tag}[^>]*class="([^"]*)"`).exec(html);
  return match?.[1] ?? "";
}

describe("ChatMarkdown", () => {
  // 메시지 목록을 그리는 화면은 입력창 글자와 스트리밍 청크마다 다시 렌더된다. 본문이 그대로인 메시지까지
  // 매번 마크다운을 다시 파싱하지 않도록, props(전부 원시값)가 같으면 렌더를 건너뛰어야 한다.
  it("skips re-rendering when props are shallowly equal", () => {
    expect(Reflect.get(ChatMarkdown, "$$typeof")).toBe(Symbol.for("react.memo"));
    // 사용자 정의 비교 없이 기본 얕은 비교를 쓴다 — props 가 원시값뿐이라 그것으로 충분하다.
    expect(Reflect.get(ChatMarkdown, "compare")).toBeNull();
  });

  it("wraps content in a Korean-aware body container", () => {
    const container = classOf(render("안녕"), "div");
    expect(container).toContain("break-keep");
    expect(container).toContain("wrap-break-word");
    expect(container).toContain("text-sm");
    expect(container).toContain("leading-relaxed");
    expect(container).toContain("text-foreground");
  });

  it("renders narration without italics in the muted color", () => {
    const em = classOf(render('*둘러본다* "누구 있어요?"'), "em");
    expect(em).toContain("not-italic");
    expect(em).toContain("text-muted-foreground");
  });

  it("renders strong as semibold", () => {
    expect(classOf(render("**강조**"), "strong")).toContain("font-semibold");
  });

  it("renders a scene header blockquote small, muted and with a 1px neutral rule", () => {
    const blockquote = classOf(render("> D+0 | 13:00 | 장소"), "blockquote");
    expect(blockquote).toContain("text-xs");
    expect(blockquote).toContain("text-muted-foreground");
    expect(blockquote).toContain("border-l");
    expect(blockquote).toContain("border-border");
    expect(blockquote).not.toContain("border-l-2");
  });

  it("renders hr as a 1px border-colored rule", () => {
    const hr = classOf(render("텍스트\n\n---"), "hr");
    expect(hr).toContain("h-px");
    expect(hr).toContain("bg-border");
  });

  it("renders inline code without a monospace face", () => {
    const code = classOf(render("`a*b`"), "code");
    expect(code).not.toContain("font-mono");
  });

  describe("code block", () => {
    it("uses monospace, small text and the muted surface by default", () => {
      const pre = classOf(render("```\n상태\n```"), "pre");
      expect(pre).toContain("font-mono");
      expect(pre).toContain("text-xs");
      expect(pre).toContain("bg-muted");
    });

    // 다이얼로그(popover/card 면) 안에서는 bg-muted 가 면과 같은 값이라 코드 면이 사라진다.
    it("switches to the secondary surface when asked", () => {
      const pre = classOf(render("```\n상태\n```", { codeBlockSurface: "secondary" }), "pre");
      expect(pre).toContain("bg-secondary");
      expect(pre).not.toContain("bg-muted");
    });

    it("ignores and hides the language tag", () => {
      const html = render("```info\n상태\n```");
      expect(html).not.toContain("info");
      expect(html).toContain("<code>상태</code>");
    });

    it("has a Korean-labelled copy button whose hover differs from the code surface", () => {
      const html = render("```\n상태\n```");
      expect(html).toContain('aria-label="코드 복사"');
      const button = classOf(html, "button");
      expect(button).not.toContain("hover:bg-muted");
      expect(button).not.toContain("hover:bg-secondary");
    });

    it("hides the copy icon from assistive technology (the button carries the label)", () => {
      expect(render("```\n상태\n```")).toMatch(/<svg[^>]*aria-hidden="true"/);
    });
  });

  it("hides a trailing lone star line instead of an empty list", () => {
    expect(render("*")).not.toContain("<ul");
    expect(render("*a\n\n*")).not.toContain("<ul");
  });
});
