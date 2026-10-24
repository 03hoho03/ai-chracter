import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { toTurnIndex, type OutlineTurn } from "../model/outlineEdits";

import { OutlineEpisodeItem } from "./OutlineEpisodeItem";

const TURNS: OutlineTurn[] = [
  { key: "u1", number: 1, messageIds: ["u1", "a1"], responseIds: ["a1"], excerpt: "첫째", hasResponse: true },
  { key: "u2", number: 2, messageIds: ["u2", "a2", "a2b"], responseIds: ["a2", "a2b"], excerpt: "둘째", hasResponse: true },
  { key: "u3", number: 3, messageIds: ["u3", "a3"], responseIds: ["a3"], excerpt: "셋째", hasResponse: true },
];

function render(extra: Partial<ComponentProps<typeof OutlineEpisodeItem>> = {}) {
  const noop = () => {};
  return renderToStaticMarkup(
    createElement(OutlineEpisodeItem, {
      episode: {
        localId: "k1",
        key: "k1",
        title: "그날 밤",
        summary: "줄거리",
        goal: "",
        basis: [{ startMessageId: "u1", endMessageId: "a3" }],
        chapterId: null,
      },
      ordinal: 2,
      count: 2,
      turnIndex: toTurnIndex(TURNS),
      turnsStatus: "ready",
      canEdit: true,
      isEditing: false,
      isSplitting: false,
      mergeBlockedReason: undefined,
      moveBlockedReasons: { up: undefined, down: undefined },
      titleMaxLength: 100,
      turnCapNotice: undefined,
      onEdit: noop,
      onApply: noop,
      onCancelEdit: noop,
      onMove: noop,
      onMerge: noop,
      onStartSplit: noop,
      onCancelSplit: noop,
      onSplit: noop,
      onRemove: noop,
      ...extra,
    }),
  );
}

describe("구성안 화의 턴 상한 안내 줄", () => {
  it("안내가 없으면 그리지 않는다", () => {
    expect(render()).not.toContain("data-turn-cap-notice");
  });

  it("일부 모델만 넘는 화는 무채 안내 + 나누기 바로가기다", () => {
    const html = render({ turnCapNotice: { tone: "partial", message: "이 화는 25턴이라 원고는 Gemini 로만 쓸 수 있어요." } });
    expect(html).toContain('data-turn-cap-notice="partial"');
    expect(html).toContain("이 화는 25턴이라 원고는 Gemini 로만 쓸 수 있어요.");
    expect(html).toContain('aria-label="2화 나누기"');
    // 강조색·위험 틴트는 쓰지 않는다 — 다른 모델로는 쓸 수 있는 화라 오류가 아니다.
    const noticeClass = /data-turn-cap-notice="partial" class="([^"]*)"/.exec(html)?.[1];
    expect(noticeClass).toBeDefined();
    expect(noticeClass).not.toMatch(/destructive|primary/);
  });

  it("고칠 수 없는 화(원고 있음·고치기 막힘)에는 나누기 바로가기가 없다", () => {
    const notice = { tone: "partial" as const, message: "안내" };
    expect(render({ turnCapNotice: notice, canEdit: false })).not.toContain("2화 나누기");
    expect(render({ turnCapNotice: notice, isSplitting: true })).not.toContain('aria-label="2화 나누기"');
  });

  it("나눌 자리마다 앞뒤 턴 수(응답 수)를 단다", () => {
    const html = render({ isSplitting: true });
    expect(html).toContain("앞 1턴 · 뒤 3턴");
    expect(html).toContain("앞 3턴 · 뒤 1턴");
  });
});
