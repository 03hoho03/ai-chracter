import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StatGaugePanel } from "./StatGaugePanel";

function render(scene?: { place: string | undefined; time: string | undefined }) {
  return renderToStaticMarkup(createElement(StatGaugePanel, { stats: [], values: {}, scene }));
}

/** 장면 줄에서 글자 `text` 를 감싼 span 의 class. */
function classOfText(html: string, text: string) {
  return html.match(new RegExp(`<span class="([^"]*)">${text}</span>`))?.[1];
}

describe("StatGaugePanel", () => {
  // 스탯이 없는 작품에서 첫 장면이 생기는 턴에 안내를 품은 라이브 영역이 처음 삽입되면 스크린리더가 읽지 않는다 — 빈 영역이
  // 먼저 DOM 에 있어야 하고, 장면이 생겨도 같은 자리(바깥 상자의 첫 자식)라야 다시 마운트되지 않는다. 보이는 줄은 없다.
  it("keeps an empty live region in place when there are no stats and no scene yet", () => {
    const liveRegion = '<div aria-live="polite" aria-atomic="true" class="sr-only"></div>';
    expect(render()).toBe(`<div class="shrink-0">${liveRegion}</div>`);
    expect(render({ place: "카페 뒷골목", time: undefined })).toMatch(new RegExp(`^<div class="shrink-0 border-b border-border">${liveRegion}<div `));
  });

  // 시간 칸의 상한이 내용 폭으로 줄어든 묶음의 절반이면 짧은 시간도 늘 잘린다 — 상한은 줄 폭(컨테이너)을 기준으로 잰다.
  it("caps the time next to a place at half of the line, not half of the shrunken text", () => {
    const html = render({ place: "카페 뒷골목", time: "밤 11시" });
    expect(html).toContain('class="@container');
    expect(classOfText(html, "밤 11시")?.split(" ")).toEqual(expect.arrayContaining(["max-w-[50cqw]", "shrink-0", "truncate"]));
    expect(classOfText(html, "카페 뒷골목")?.split(" ")).toEqual(expect.arrayContaining(["min-w-0", "truncate"]));
  });

  it("lets a time without a place use the whole line", () => {
    const timeClass = classOfText(render({ place: undefined, time: "밤 11시" }), "밤 11시");
    expect(timeClass?.split(" ")).toEqual(expect.arrayContaining(["min-w-0", "truncate"]));
    expect(timeClass).not.toMatch(/max-w-|shrink-0/);
  });

  // 보이는 스탯이 없고(전부 숨긴 스탯) 장면도 없는 방에서 숨긴 스탯이 바뀐 턴 — 라이브 영역이 "무언가 달라졌다"를 읽으니
  // 화면에도 같은 신호가 보여야 한다. 장면 줄 자리에 신호만 서고, 접을 칸이 없어 접기 버튼은 없다.
  it("shows the anonymous signal line without a scene when no stats are visible", () => {
    const html = renderToStaticMarkup(
      createElement(StatGaugePanel, {
        stats: [],
        values: {},
        feedback: { turn: 1, roomId: "room", messageId: "message", deltas: {}, hiddenSignal: true, announcement: "무언가 달라졌다" },
      }),
    );
    expect(html).toMatch(/^<div class="shrink-0 border-b border-border">/);
    expect(html.match(/무언가 달라졌다/g)).toHaveLength(2);
    expect(html).not.toContain("지금 장면");
    expect(html).not.toContain("상태 줄");
  });

  it("does not fade the scene drawn on entry", () => {
    expect(render({ place: "카페 뒷골목", time: undefined })).not.toContain("fade-in");
  });
});
