// 담을 대화 타임라인의 마크업 — 턴 버튼의 눌림 상태, 잠긴 대화의 접힘, 뺀 대화 묶음의 "맥락으로 보내기" 동의와 접힘.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { buildSourceTurns, type SourceMessage, type TurnState } from "../model/sourceTimeline";

import { SourceTimeline } from "./SourceTimeline";

function room(turnCount: number): SourceMessage[] {
  const messages: SourceMessage[] = [{ id: "a0", role: "assistant", content: "첫 인사" }];
  for (let n = 1; n <= turnCount; n += 1) {
    messages.push({ id: `u${n}`, role: "user", content: `말 ${n}` });
    messages.push({ id: `a${n}`, role: "assistant", content: `답 ${n}` });
  }
  return messages;
}

const turns = buildSourceTurns(room(9), {
  fixedEndId: "a9",
  roomEndId: "a9",
  lockedRanges: [{ startMessageId: "a0", endMessageId: "a1" }],
});

// 1·2턴 잠김, 3턴 담기, 4턴 빼기(짧은 묶음), 5턴 담기, 6~9턴 빼기(긴 묶음), 10턴 맥락.
const states = new Map<string, TurnState>([
  ["a0", "locked"],
  ["u1", "locked"],
  ["u2", "include"],
  ["u3", "exclude"],
  ["u4", "include"],
  ["u5", "exclude"],
  ["u6", "exclude"],
  ["u7", "exclude"],
  ["u8", "exclude"],
  ["u9", "context"],
]);

function render(expandedGapKeys: string[] = [], changedKeys: string[] = []): string {
  return renderToStaticMarkup(
    createElement(SourceTimeline, {
      turns,
      states,
      changedKeys: new Set(changedKeys),
      expandedGapKeys: new Set(expandedGapKeys),
      onToggleTurn: () => {},
      onSetGap: () => {},
      onToggleGapExpanded: () => {},
    }),
  );
}

/** 턴 버튼(`data-turn` 가 붙은 버튼)의 여는 태그. */
function turnButton(html: string, number: number): string {
  return new RegExp(`<button[^>]*data-turn="${number}"[^>]*>`).exec(html)?.[0] ?? "";
}

describe("SourceTimeline", () => {
  it("담은 턴은 눌린 버튼, 뺀 턴·맥락 턴은 눌리지 않은 버튼이다", () => {
    const html = render();
    expect(turnButton(html, 3)).toContain('aria-pressed="true"');
    expect(turnButton(html, 4)).toContain('aria-pressed="false"');
    expect(turnButton(html, 10)).toContain('aria-pressed="false"');
  });

  it("잠긴 대화는 버튼 없는 한 줄로 접는다", () => {
    const html = render();
    expect(html).toContain("이미 쓴 대화 1~2턴");
    expect(turnButton(html, 1)).toBe("");
    expect(turnButton(html, 2)).toBe("");
  });

  it("뺀 대화 묶음마다 맥락으로 보내기 동의가 있고, 그 이름이 어느 턴인지 말한다", () => {
    const html = render();
    expect(html).toContain('aria-label="4턴을 맥락으로 보내기"');
    expect(html).toContain('aria-label="6~9턴을 맥락으로 보내기"');
    expect(html).toContain('aria-label="10턴을 맥락에서 빼기"');
  });

  it("긴 뺀 대화 묶음은 접혀 있다가 펼치면 턴이 보인다. 짧은 묶음은 늘 펼쳐 있다", () => {
    const folded = render();
    expect(turnButton(folded, 4)).not.toBe("");
    expect(turnButton(folded, 6)).toBe("");
    expect(folded).toMatch(/<button[^>]*aria-expanded="false"[^>]*>펼치기/);
    const opened = render(["u5"]);
    expect(turnButton(opened, 6)).not.toBe("");
    expect(opened).toMatch(/<button[^>]*aria-expanded="true"[^>]*>접기/);
  });

  it("원문이 바뀐 턴에 표시를 단다", () => {
    const html = render([], ["u4"]);
    const row = /data-turn="5"[\s\S]*?<\/button>/.exec(html)?.[0] ?? "";
    expect(row).toContain("바뀜");
    expect(/data-turn="3"[\s\S]*?<\/button>/.exec(html)?.[0]).not.toContain("바뀜");
  });
});
