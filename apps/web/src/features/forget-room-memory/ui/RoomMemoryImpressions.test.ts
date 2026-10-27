// 노트·요약 탭의 관계 인상 구획. 서버가 칸을 비우면(null → 없는 값) 구획이 없고, 빈 목록이면 빈 상태 문장, 있으면 가장 최근
// 인상 하나만 전문으로 보이고 이전 것은 버튼 하나로 접혀 있다.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ChatRoomMemoryImpression } from "@/entities/chat-room";

import { MemoryImpressionsSection, MemoryImpressionsView } from "./RoomMemoryImpressions";

function impression(id: string, text: string, overrides: Partial<ChatRoomMemoryImpression> = {}): ChatRoomMemoryImpression {
  return {
    id,
    text,
    createdAt: "2026-10-27T01:00:00Z",
    turnStart: 61,
    turnEnd: 92,
    sceneCount: 9,
    factCount: 4,
    ...overrides,
  };
}

const LATEST = impression("i3", "처음엔 경계하던 서아가 이제는 먼저 안부를 묻는다.");
const MIDDLE = impression("i2", "서아가 점장의 비밀을 알게 된 뒤 거리를 둔다.", { turnStart: 31, turnEnd: 60 });
const OLDEST = impression("i1", "서로 이름도 모르던 사이.", { turnStart: 1, turnEnd: 30 });

function renderSection(impressions: ChatRoomMemoryImpression[] | undefined): string {
  return renderToStaticMarkup(createElement(MemoryImpressionsSection, { impressions }));
}

function renderView(impressions: ChatRoomMemoryImpression[], isOlderOpen: boolean): string {
  return renderToStaticMarkup(createElement(MemoryImpressionsView, { impressions, isOlderOpen, onToggleOlder: () => {} }));
}

/** 이전 인상 토글 버튼의 여는 태그. */
function toggleButton(markup: string): string | undefined {
  return /<button[^>]*aria-expanded[^>]*>/.exec(markup)?.[0];
}

/** 이전 인상 목록의 여는 태그. */
function olderList(markup: string): string | undefined {
  return /<ul[^>]*>/.exec(markup)?.[0];
}

describe("MemoryImpressionsSection", () => {
  it("서버가 인상 칸을 비우면 구획을 그리지 않는다", () => {
    expect(renderSection(undefined)).toBe("");
  });

  it("빈 목록이면 제목과 앞으로 쌓인다는 빈 상태 문장을 보이고 토글은 없다", () => {
    const markup = renderSection([]);
    expect(markup).toContain("관계의 인상");
    expect(markup).toContain("아직 쌓인 인상이 없어요.");
    expect(toggleButton(markup)).toBeUndefined();
  });

  it("인상이 하나면 전문과 턴 범위·근거 개수를 보이고 토글은 없다", () => {
    const markup = renderSection([LATEST]);
    expect(markup).toContain(LATEST.text);
    expect(markup).toContain("61~92번째 턴");
    expect(markup).toContain("장면 9개 · 사실 4개에서");
    expect(toggleButton(markup)).toBeUndefined();
  });

  it("여럿이면 처음엔 이전 인상이 접혀 있다", () => {
    const markup = renderSection([LATEST, MIDDLE, OLDEST]);
    const button = toggleButton(markup);
    expect(button).toContain('aria-expanded="false"');
    expect(markup).toContain("이전 인상 2개");
    expect(olderList(markup)).toContain("hidden");
  });

  it("응답에 쓰이지 않는다는 것과 잊기로 함께 지워진다는 것을 말한다", () => {
    const markup = renderSection([LATEST]);
    expect(markup).toContain("캐릭터의 응답에는 쓰이지 않아요.");
    expect(markup).toContain("근거가 된 장면이나 사실을 잊게 하면 그 인상도 함께 지워져요.");
  });
});

describe("MemoryImpressionsView", () => {
  it("최근 인상은 접힘과 상관없이 전문으로 보이고 이전 인상은 숨긴 목록 안에 있다", () => {
    const markup = renderView([LATEST, MIDDLE, OLDEST], false);
    expect(markup.indexOf(LATEST.text)).toBeLessThan(markup.indexOf("<ul"));
    expect(markup.indexOf(MIDDLE.text)).toBeGreaterThan(markup.indexOf("<ul"));
    expect(markup.indexOf(OLDEST.text)).toBeGreaterThan(markup.indexOf(MIDDLE.text));
  });

  it("토글은 숨긴 목록을 가리킨다", () => {
    const markup = renderView([LATEST, MIDDLE], false);
    const controls = /aria-controls="([^"]+)"/.exec(toggleButton(markup) ?? "")?.[1];
    expect(controls).toBeDefined();
    expect(olderList(markup)).toContain(`id="${controls}"`);
  });

  it("펼치면 목록이 보이고 토글이 접기로 바뀐다", () => {
    const markup = renderView([LATEST, MIDDLE, OLDEST], true);
    expect(toggleButton(markup)).toContain('aria-expanded="true"');
    expect(markup).toContain("이전 인상 접기");
    expect(olderList(markup)).not.toContain("hidden");
  });

  it("턴 범위나 근거가 없는 인상은 그 표시를 빼고 본문만 보인다", () => {
    const bare = impression("x", "근거가 다 지워진 인상.", {
      turnStart: undefined,
      turnEnd: undefined,
      sceneCount: 0,
      factCount: 0,
    });
    const markup = renderView([bare], false);
    expect(markup).toContain("근거가 다 지워진 인상.");
    expect(markup).not.toContain("번째 턴");
    expect(markup).not.toContain("개에서");
  });
});
