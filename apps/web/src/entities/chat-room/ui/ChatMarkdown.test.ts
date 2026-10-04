// 이 사례들은 DESIGN.md 의 채팅 표기 절과 같아야 한다 — 표기 규칙을 바꾸면 그 절과 이 표를 함께 고친다.
// 구조는 모델 테스트가 보고, 여기서는 표기마다 입히는 스타일 계약만 본다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatMarkdown } from "./ChatMarkdown";
import type { AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import { AuthorMacroNamesProvider } from "./AuthorMacroNamesProvider";
import { MediaTagImagesProvider } from "./MediaTagImagesProvider";

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

  // 글 속 미디어 북 태그는 그림 맵으로 감싼 메시지(작성자 글)에서만 그림이 된다. 사용자 메시지·스트리밍 응답은 감싸지
  // 않으므로 태그가 글자 그대로다 — 사용자가 칸 id 를 쳐서 그림을 불러내지 못한다.
  describe("media tag images", () => {
    const CELL = "aaaaaaaa-0000-0000-0000-000000000001";
    const GONE = "bbbbbbbb-0000-0000-0000-000000000009";
    const images = { [CELL]: { url: "https://cdn.example/a.webp", width: 1024, height: 768 } };

    function renderWithImages(content: string, options: RenderOptions = {}): string {
      return renderToStaticMarkup(
        createElement(MediaTagImagesProvider, { images, children: createElement(ChatMarkdown, { content, ...options }) }),
      );
    }

    it("leaves tags as text when no image map is given", () => {
      const html = render(`앞 {{img::${CELL}}} 뒤`);
      expect(html).toContain(`{{img::${CELL}}}`);
      expect(html).not.toContain("<img");
    });

    it("draws a mapped tag as an image block at its own aspect ratio", () => {
      const html = renderWithImages(`앞\n\n{{img::${CELL}}}\n\n뒤`);
      expect(html).toContain('src="https://cdn.example/a.webp"');
      expect(html).toContain("aspect-ratio:1024 / 768");
      expect(html).not.toContain(`{{img::${CELL}}}`);
    });

    it("leaves a blank, not the raw tag, for a cell missing from the map", () => {
      const html = renderWithImages(`앞\n\n{{img::${GONE}}}\n\n뒤`);
      expect(html).not.toContain(GONE);
      expect(html).not.toContain("<img");
      expect(html).toContain("<p class=\"m-0\">앞</p>");
    });

    // 빈칸은 글을 쪼개지 않는다 — 문장 중간의 지워진 칸 때문에 한 문장이 두 문단으로 갈라지면 안 된다.
    it("keeps a sentence in one paragraph around a cell missing from the map", () => {
      expect(renderWithImages(`앞 {{img::${GONE}}} 뒤`)).toContain('<p class="m-0">앞  뒤</p>');
    });

    it("keeps name-form tags as text even where a map is given", () => {
      expect(renderWithImages("{{img::민아/교실}}")).toContain("{{img::민아/교실}}");
    });

    it("uses the secondary surface for the image well inside dialogs", () => {
      const html = renderWithImages(`{{img::${CELL}}}`, { codeBlockSurface: "secondary" });
      expect(html).toMatch(/class="self-start overflow-hidden rounded-lg bg-secondary"/);
      expect(html).not.toMatch(/rounded-lg bg-muted/);
    });
  });

  // 글 속 `{{user}}`·`{{char}}` 는 이름으로 감싼 메시지(작성자 글)에서만 바뀐다. 사용자 메시지는 보낼 때 이미 바꿨고,
  // 모델 응답은 작성자 글이 아니라 감싸지 않는다.
  describe("author macro names", () => {
    const CELL = "aaaaaaaa-0000-0000-0000-000000000001";
    const images = { [CELL]: { url: "https://cdn.example/a.webp", width: 1024, height: 768 } };

    function renderWithNames(content: string, names: AuthorMacroNames = { userName: "지훈", charName: null }): string {
      return renderToStaticMarkup(
        createElement(AuthorMacroNamesProvider, { names, children: createElement(ChatMarkdown, { content }) }),
      );
    }

    it("puts the name in and fixes the particle right after it", () => {
      expect(renderWithNames("*문이 열린다.* {{user}}는 고개를 든다.")).toContain(
        '<p class="m-0"><em class="not-italic text-muted-foreground">문이 열린다.</em> 지훈은 고개를 든다.</p>',
      );
    });

    it("leaves the macros as written when no names are given", () => {
      expect(render("{{user}}는 고개를 든다.")).toContain("{{user}}는 고개를 든다.");
    });

    it("names {{char}} only when a character name is given", () => {
      expect(renderWithNames("{{char}}가 웃는다.", { userName: "지훈", charName: "유나" })).toContain("유나가 웃는다.");
      expect(renderWithNames("{{char}}가 웃는다.")).toContain("{{char}}가 웃는다.");
    });

    it("draws the opening message's images and names together", () => {
      const html = renderToStaticMarkup(
        createElement(AuthorMacroNamesProvider, {
          names: { userName: "하늘", charName: null },
          children: createElement(MediaTagImagesProvider, {
            images,
            children: createElement(ChatMarkdown, { content: `{{user}}으로부터\n\n{{img::${CELL}}}\n\n{{user}}으로` }),
          }),
        }),
      );
      expect(html).toContain('src="https://cdn.example/a.webp"');
      // 뒤가 한글이면 조사가 아니라 낱말의 일부라 두고, 글 끝의 조사는 ㄹ 받침에 맞춘다.
      expect(html).toContain("하늘으로부터");
      expect(html).toContain("하늘로");
    });
  });
});
