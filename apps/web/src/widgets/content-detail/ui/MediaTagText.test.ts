// 상세의 작성자 글은 평문 그대로이고 칸 id 형태 태그 자리에만 그림 블록이 선다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MediaTagText } from "./MediaTagText";

const CELL = "aaaaaaaa-0000-0000-0000-000000000001";
const GONE = "bbbbbbbb-0000-0000-0000-000000000009";
const IMAGES = { [CELL]: { url: "https://cdn.example/a.webp", width: 768, height: 1024 } };

const NAMES = { userName: "지훈", charName: null };

function render(text: string, surface: "muted" | "secondary" = "muted"): string {
  return renderToStaticMarkup(
    createElement(MediaTagText, { text, images: IMAGES, names: NAMES, className: "prose-line", surface }),
  );
}

describe("MediaTagText", () => {
  it("keeps tagless text as the single plain paragraph it was, markdown characters included", () => {
    expect(render("# 제목 아님\n*별표*")).toBe('<p class="prose-line"># 제목 아님\n*별표*</p>');
  });

  it("puts an image block between the paragraphs around the tag", () => {
    const html = render(`앞 문단\n\n{{img::${CELL}}}\n\n뒤 문단`);
    expect(html).toMatch(
      /^<div class="flex flex-col gap-3"><p class="prose-line">앞 문단<\/p><div [^>]*style="aspect-ratio:768 \/ 1024[^"]*"><img src="https:\/\/cdn.example\/a.webp"[^>]*\/><\/div><p class="prose-line">뒤 문단<\/p><\/div>$/,
    );
  });

  it("leaves a blank for a cell missing from the map", () => {
    expect(render(`앞\n\n{{img::${GONE}}}\n\n뒤`)).toBe('<p class="prose-line">앞\n\n뒤</p>');
  });

  it("paints the image well with the surface it is given", () => {
    expect(render(`{{img::${CELL}}}`, "secondary")).toContain("bg-secondary");
  });

  // 상세는 방이 없어 보는 사람의 이름으로 바꾼다. 그림 태그를 가른 뒤 글 조각마다 바꾸므로 그림 양옆의 글도 바뀐다.
  it("puts the name into the text on both sides of an image block, fixing the particle", () => {
    const html = render(`{{user}}는 문을 연다.\n\n{{img::${CELL}}}\n\n{{user}}가 웃는다.`);
    expect(html).toContain('<p class="prose-line">지훈은 문을 연다.</p>');
    expect(html).toContain('<p class="prose-line">지훈이 웃는다.</p>');
  });

  it("puts the name into a tagless text too", () => {
    expect(render("{{USER}}를 기다린다")).toBe('<p class="prose-line">지훈을 기다린다</p>');
  });
});
