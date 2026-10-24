// 대화로 바로 만든 화(옛 흐름 화)의 다시 만들기 버튼. 구성안으로 쓴 화의 다시 만들기를 더해도 옛 화의 버튼은 지금까지와 글자
// 하나까지 같아야 한다 — 이름·잠김·사유 가리키기·방이 지워진 소설에서 사라지기.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { NovelChapterJobFlow } from "../model/useNovelChapterJob";

import { RegenerateChapterButton } from "./RegenerateChapterButton";

const idleFlow = {
  statusId: "status",
  preparing: undefined,
  isJobRunning: false,
  isAiEditRunning: false,
  isRoomGone: false,
  isBusy: false,
  hasPollError: false,
  runningKind: undefined,
  runningRangeLabel: undefined,
  chainProgress: undefined,
  notice: undefined,
  startCreate: () => Promise.resolve(),
  startRegenerate: () => Promise.resolve(),
  retry: () => {},
} as unknown as NovelChapterJobFlow;

const single = { id: "c1", batchId: "b1", ordinal: 1, episodeOutlineId: null };
const inRange = { id: "c2", batchId: "b2", ordinal: 2, episodeOutlineId: null };
const chapters = [single, inRange, { id: "c3", batchId: "b2", ordinal: 3, episodeOutlineId: null }];

function render(
  flow: Partial<Record<keyof NovelChapterJobFlow, unknown>>,
  chapter: typeof single,
  extra: { isBlocked?: boolean; blockedReasonId?: string } = {},
): string {
  return renderToStaticMarkup(
    createElement(RegenerateChapterButton, {
      flow: { ...idleFlow, ...flow } as unknown as NovelChapterJobFlow,
      chapter,
      chapters,
      ...extra,
    }),
  );
}

describe("옛 흐름 화의 다시 만들기 버튼", () => {
  it("혼자 만든 화", () => {
    expect(render({}, single)).toMatchSnapshot();
  });

  it("함께 만든 화들", () => {
    expect(render({}, inRange)).toMatchSnapshot();
  });

  it("화 작업이 도는 중", () => {
    expect(render({ isJobRunning: true, isBusy: true }, inRange)).toMatchSnapshot();
  });

  it("AI 수정 중이라 막힘", () => {
    expect(render({}, single, { isBlocked: true, blockedReasonId: "ai-edit" })).toMatchSnapshot();
  });

  it("대화방이 지워진 소설", () => {
    expect(render({ isRoomGone: true }, single)).toBe("");
  });
});
