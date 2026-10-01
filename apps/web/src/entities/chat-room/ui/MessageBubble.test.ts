// 판정 이미지 슬롯은 캐릭터 상황별 이미지와 스토리 미디어 북 그림이 함께 쓴다. 캐릭터 메시지에는 서버가 크기를 싣지
// 않으므로 그 화면은 지금까지의 3:4 웰 그대로여야 하고, 크기를 아는 그림만 원본 비율로 그린다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../api/chatStream";
import { MessageBubble } from "./MessageBubble";
// 컴포넌트를 렌더할 DOM 이 없는 node 환경이라 메뉴 구성은 소스로 확인한다(닫힌 메뉴는 정적 마크업에 그려지지 않는다).
import bubbleSource from "./MessageBubble.tsx?raw";

function render(message: ChatMessage): string {
  return renderToStaticMarkup(createElement(MessageBubble, { message }));
}

const CHARACTER_MESSAGE: ChatMessage = {
  id: "m1",
  role: "assistant",
  content: "안녕",
  imageId: "i1",
  imageUrl: "https://x/y.png",
  createdAt: "",
};

describe("MessageBubble judged image slot", () => {
  // 원본 비율을 들이기 전 이 컴포넌트가 그리던 마크업을 글자 그대로 옮겨 둔 회귀선이다.
  it("renders an image without dimensions exactly as the fixed 3:4 well it always was", () => {
    expect(render(CHARACTER_MESSAGE)).toBe(
      '<div class="flex w-full flex-col gap-1.5"><div class="flex items-start gap-1"><div class="flex min-w-0 flex-col gap-3 break-keep wrap-break-word text-sm leading-relaxed text-foreground max-w-3xl"><p class="m-0">안녕</p></div></div><div class="self-start aspect-3/4 h-80 max-w-3/4 overflow-hidden rounded-lg bg-muted"><img src="https://x/y.png" alt="대화 중 노출된 이미지" loading="lazy" decoding="async" class="size-full object-contain"/></div></div>',
    );
  });

  it("falls back to the fixed well when only one dimension is known", () => {
    expect(render({ ...CHARACTER_MESSAGE, imageWidth: 800 })).toContain("aspect-3/4 h-80 max-w-3/4");
  });

  it("reserves the image's own aspect ratio when the message carries its size", () => {
    const html = render({ ...CHARACTER_MESSAGE, imageWidth: 1200, imageHeight: 800 });
    expect(html).toContain('style="aspect-ratio:1200 / 800;width:480px;max-width:100%"');
    expect(html).not.toContain("aspect-3/4");
  });
});

describe("MessageBubble options menu", () => {
  // 파괴 항목(삭제)이 맨 끝에 오도록 신고는 그 앞에 둔다.
  it("orders the items as regenerate, edit, report, delete", () => {
    const positions = ["다시 생성", "수정", "신고", "삭제"].map((label) => bubbleSource.indexOf(`${label}\n`));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });

  // 신고만 받는 버블(삭제 콜백 없음)에서도 메뉴가 그려져야 한다.
  it("renders the menu when either delete or report is provided", () => {
    expect(bubbleSource).toContain("{(onDelete || onReport) && (");
  });

  it("does not style report as destructive — it removes no data", () => {
    expect(bubbleSource).toMatch(/<DropdownMenuItem onSelect=\{\(\) => onReport\(/);
  });
});
