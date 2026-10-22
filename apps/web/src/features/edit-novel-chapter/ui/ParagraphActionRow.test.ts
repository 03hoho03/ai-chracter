// 고른 문단 아래 동작 줄. 스위치가 꺼져 있으면 지금 화면 그대로 셋이고, 켜져 있으면 그림 붙이기가 더해진다. 붙이기는 한 화의
// 상한에 닿았거나 이 화를 다시 만드는 중이면 막히고 그 까닭을 단다.
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CHAPTER_REGENERATING_MESSAGE } from "@/entities/novel";

import { toParagraphActions } from "../model/boardIllustrations";
import { ParagraphActionRow } from "./ParagraphActionRow";

function render(overrides: Partial<ComponentProps<typeof ParagraphActionRow>> & { isIllustrationsOn: boolean }): string {
  const { isIllustrationsOn, ...rest } = overrides;
  return renderToStaticMarkup(
    createElement(ParagraphActionRow, {
      actions: toParagraphActions({ isMoving: false, isIllustrationsOn }),
      isAiBlocked: false,
      isRegenerating: false,
      blockedReason: undefined,
      reasonId: "reason",
      isLimitReached: false,
      isAttachBusy: false,
      attachPendingLabel: undefined,
      onAiEdit: () => {},
      onManualEdit: () => {},
      onClearSelection: () => {},
      onAttach: () => {},
      ...rest,
    }),
  );
}

/** "그림 붙이기" 버튼의 여는 태그. */
function attachButton(markup: string): string | undefined {
  return /<button[^>]*>(?:(?!<\/button>).)*그림 붙이기/s.exec(markup)?.[0];
}

describe("ParagraphActionRow", () => {
  it("스위치가 꺼졌으면 지금 그대로 세 버튼이고 그림 붙이기가 없다", () => {
    const markup = render({ isIllustrationsOn: false });
    expect(markup).toContain("AI로 고치기");
    expect(markup).toContain("직접 고치기");
    expect(markup).toContain("선택 해제");
    expect(markup).not.toContain("그림 붙이기");
    expect(markup.match(/<button/g)).toHaveLength(3);
  });

  it("스위치가 켜졌으면 그림 붙이기가 있고 누를 수 있다", () => {
    const button = attachButton(render({ isIllustrationsOn: true }));
    expect(button).toBeDefined();
    expect(button).not.toContain('aria-disabled="true"');
  });

  // 서버가 409 로 막을 요청을 미리 막는다 — 위치 확인 필요인 그림도 센 수다.
  it("한 화의 상한에 닿았으면 붙이기를 막고 떼면 넣을 수 있다고 말한다", () => {
    const markup = render({ isIllustrationsOn: true, isLimitReached: true });
    expect(attachButton(markup)).toContain('aria-disabled="true"');
    expect(markup).toContain("한 화에는 삽화를 10장까지 넣을 수 있어요. 다른 삽화를 떼면 넣을 수 있어요.");
  });

  // 다시 만든 판은 문단이 모두 새것이라 지금 붙인 그림이 곧 위치 확인 필요로 옮겨진다.
  it("이 화를 다시 만드는 중이면 붙이기를 막고 그 까닭을 단다", () => {
    const markup = render({
      isIllustrationsOn: true,
      isRegenerating: true,
      blockedReason: CHAPTER_REGENERATING_MESSAGE,
    });
    expect(attachButton(markup)).toContain('aria-disabled="true"');
    expect(markup).toContain(CHAPTER_REGENERATING_MESSAGE);
  });

  it("올리거나 붙이는 중이면 붙이기를 막고 진행 문구를 보인다", () => {
    const markup = render({ isIllustrationsOn: true, isAttachBusy: true, attachPendingLabel: "올리는 중…" });
    expect(markup).toContain("올리는 중…");
    expect(/<button[^>]*aria-disabled="true"[^>]*>(?:(?!<\/button>).)*올리는 중…/s.test(markup)).toBe(true);
  });
});
