import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CREATION_GUIDE_TOPIC_IDS, type CreationGuidePath, creationGuidePath } from "@/shared/config/creationGuide";

import { BuilderTopBarActions } from "./BuilderTopBarActions";

function renderActions(
  guidePath: CreationGuidePath,
  preview: { isPreviewOpen?: boolean; previewLabel?: string } = {},
): string {
  return renderToStaticMarkup(
    createElement(BuilderTopBarActions, {
      guidePath,
      isPublishing: false,
      isPreviewOpen: preview.isPreviewOpen ?? false,
      previewLabel: preview.previewLabel,
      onPreview: () => {},
      onSaveNow: () => {},
      onPublish: () => {},
    }),
  );
}

function guideLinkOf(html: string): string {
  const match = /<a [^>]*>/.exec(html);
  return match?.[0] ?? "";
}

function previewButtonOf(html: string): string {
  const match = /<button [^>]*aria-expanded[^>]*>/.exec(html);
  return match?.[0] ?? "";
}

const STORY_GUIDE_PATH = creationGuidePath("story");

describe("BuilderTopBarActions guide link", () => {
  it.each(CREATION_GUIDE_TOPIC_IDS.map((topicId) => creationGuidePath(topicId)))("points at %s", (guidePath) => {
    expect(guideLinkOf(renderActions(guidePath))).toContain(`href="${guidePath}"`);
  });

  // 빌더는 지금 열린 탭의 단계 페이지로 건다.
  it("points at a step page of a guide", () => {
    const stepPath = creationGuidePath("story", "setting");
    expect(stepPath).toBe("/guide/story/setting");
    expect(guideLinkOf(renderActions(stepPath))).toContain('href="/guide/story/setting"');
  });

  // 같은 탭에서 이동하면 쓰던 폼을 떠나게 되므로 새 탭으로 열고, 열린 탭이 빌더 창을 조작하지 못하게 한다.
  it("opens in a new tab without an opener", () => {
    const link = guideLinkOf(renderActions(STORY_GUIDE_PATH));
    expect(link).toContain('target="_blank"');
    expect(link).toContain('rel="noopener noreferrer"');
  });

  // 좁은 화면에서는 아이콘만 남으므로 접근 가능한 이름이 따로 있어야 한다.
  it("has an accessible name that says it opens a new tab", () => {
    expect(guideLinkOf(renderActions(STORY_GUIDE_PATH))).toContain('aria-label="작성 가이드 (새 탭에서 열림)"');
  });
});

describe("BuilderTopBarActions preview toggle", () => {
  // 캐릭터 빌더와 스토리 빌더의 다른 탭은 이름을 넘기지 않는다 — 지금까지와 같은 "미리보기" 여야 한다.
  it("is called 미리보기 unless the shell names it", () => {
    expect(previewButtonOf(renderActions(STORY_GUIDE_PATH))).toContain('aria-label="미리보기"');
    expect(previewButtonOf(renderActions(STORY_GUIDE_PATH, { isPreviewOpen: true }))).toContain('aria-label="미리보기 닫기"');
  });

  // 여는 화면이 대화가 아니면 버튼이 그 화면의 이름을 말해야 누른 결과와 약속이 맞는다.
  it("uses the name the shell passes, both closed and open", () => {
    expect(previewButtonOf(renderActions(STORY_GUIDE_PATH, { previewLabel: "배치표" }))).toContain('aria-label="배치표"');
    expect(
      previewButtonOf(renderActions(STORY_GUIDE_PATH, { isPreviewOpen: true, previewLabel: "배치표" })),
    ).toContain('aria-label="배치표 닫기"');
  });
});
