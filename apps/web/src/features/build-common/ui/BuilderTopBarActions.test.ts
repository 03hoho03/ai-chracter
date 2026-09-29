import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CREATION_GUIDE_TOPIC_IDS, type CreationGuidePath, creationGuidePath } from "@/shared/config/creationGuide";

import { BuilderTopBarActions } from "./BuilderTopBarActions";

function renderActions(guidePath: CreationGuidePath): string {
  return renderToStaticMarkup(
    createElement(BuilderTopBarActions, {
      guidePath,
      isPublishing: false,
      isPreviewOpen: false,
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

const STORY_GUIDE_PATH = creationGuidePath("story");

describe("BuilderTopBarActions guide link", () => {
  it.each(CREATION_GUIDE_TOPIC_IDS.map(creationGuidePath))("points at %s", (guidePath) => {
    expect(guideLinkOf(renderActions(guidePath))).toContain(`href="${guidePath}"`);
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
