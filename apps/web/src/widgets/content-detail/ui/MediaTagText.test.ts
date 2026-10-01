// 상세의 작성자 글은 평문 그대로이고 칸 id 형태 태그 자리에만 그림 블록이 선다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MediaTagText } from "./MediaTagText";

const CELL = "aaaaaaaa-0000-0000-0000-000000000001";
const GONE = "bbbbbbbb-0000-0000-0000-000000000009";
const IMAGES = { [CELL]: { url: "https://cdn.example/a.webp", width: 768, height: 1024 } };

function render(text: string, surface: "muted" | "secondary" = "muted"): string {
  return renderToStaticMarkup(createElement(MediaTagText, { text, images: IMAGES, className: "prose-line", surface }));
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
});
