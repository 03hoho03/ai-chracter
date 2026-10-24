// 화 확인 창의 글쓰기 모델 선택. 옛 흐름 다시 만들기 창과 구성 흐름 원고 확인 창이 이 선택을 함께 쓴다 — 옛 창은 운영 화면이라 고를 수
// 있는 항목·금액 글·못 고르는 항목의 막기가 그대로인지 묶는다. 셀렉트 프리미티브는 열린 목록을 포털로 그려 서버 렌더에 나오지 않으므로,
// 항목에 넘긴 속성을 받아 두는 가짜로 바꿔 끼운다.
import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  toOutlineChapterModelOptions,
  toProposalModelOptions,
  toRegenerateModelOptions,
  type ChapterModelOption,
  type NovelChapterModelId,
} from "../model/chapterModel";
import { ChapterModelSelect } from "./ChapterModelSelect";

type ItemProps = Record<string, unknown> & { value: string; children: ReactNode };

const captured = vi.hoisted(() => ({
  items: [] as Record<string, unknown>[],
  onValueChange: undefined as ((value: string) => void) | undefined,
}));

vi.mock("@ai-character-chat/ui/components/select", () => ({
  Select: ({ children, onValueChange }: { children: ReactNode; onValueChange: (value: string) => void }) => {
    captured.onValueChange = onValueChange;
    return createElement("div", null, children);
  },
  SelectTrigger: ({ children }: { children: ReactNode }) => createElement("button", null, children),
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => createElement("div", { role: "listbox" }, children),
  SelectItem: (props: ItemProps) => {
    captured.items.push(props);
    return createElement("div", { role: "option" }, props.children);
  },
}));

function render(options: ChapterModelOption[], onValueChange: (id: NovelChapterModelId) => void = () => {}): string {
  return renderToStaticMarkup(createElement(ChapterModelSelect, { options, value: "gemini", onValueChange }));
}

function itemFor(value: string): ItemProps {
  const item = captured.items.find((props) => props.value === value);
  if (item === undefined) throw new Error(`항목 없음: ${value}`);
  return item as ItemProps;
}

beforeEach(() => {
  captured.items = [];
  captured.onValueChange = undefined;
});

// 옛 흐름 다시 만들기: 묶음 화 수·턴 수로 서버가 판정한 목록. Opus 는 턴이 길어 못 쓴다.
const REGENERATE = toRegenerateModelOptions([
  { model: "gemini", name: "Gemini", cost: 80, eligible: true, ineligibleReason: null },
  { model: "sonnet", name: "Claude Sonnet 5.5", cost: 180, eligible: true, ineligibleReason: null },
  { model: "opus", name: "Claude Opus 5.5", cost: 300, eligible: false, ineligibleReason: "too_many_turns" },
]);

describe("ChapterModelSelect — 옛 흐름 다시 만들기 창(바뀌지 않는 것)", () => {
  it("항목 글은 고를 수 있으면 금액, 못 고르면 이유다", () => {
    const html = render(REGENERATE);
    expect(html).toContain("Gemini · 클로버 80개");
    expect(html).toContain("Claude Sonnet 5.5 · 클로버 180개");
    expect(html).toContain("Claude Opus 5.5 · 대화가 길어 이 모델로는 못 써요");
    expect(html).not.toContain("클로버 300개");
  });

  it("못 고르는 모델이 골라져도 부모에게 알리지 않고, 고를 수 있는 모델은 알린다", () => {
    const picked: NovelChapterModelId[] = [];
    render(REGENERATE, (id) => picked.push(id));
    captured.onValueChange?.("opus");
    expect(picked).toEqual([]);
    captured.onValueChange?.("sonnet");
    expect(picked).toEqual(["sonnet"]);
  });

  it("고를 수 있는 모델 항목에는 아무것도 더하지 않는다", () => {
    render(REGENERATE);
    for (const value of ["gemini", "sonnet"]) {
      const item = itemFor(value);
      expect(item.disabled).toBeFalsy();
      expect(item["aria-disabled"]).toBeUndefined();
      expect(item.onKeyDown).toBeUndefined();
      expect(item.onPointerUp).toBeUndefined();
      expect(item.onClick).toBeUndefined();
      expect(item.className).toBeUndefined();
    }
  });

  it("모델이 하나뿐이면(상위 모델 허용 없음) 아무것도 그리지 않는다", () => {
    expect(render(REGENERATE.slice(0, 1))).toBe("");
  });
});

describe("ChapterModelSelect — 새 화 경계 고르기 창(바뀌지 않는 것)", () => {
  it("모든 항목을 고를 수 있고 금액 없이 이름만 보인다", () => {
    const html = render(
      toProposalModelOptions([
        { id: "gemini", name: "Gemini", chapterGenerate: 80, chapterRegenerate: 80 },
        { id: "opus", name: "Claude Opus 5.5", chapterGenerate: 300, chapterRegenerate: 300 },
      ]),
    );
    expect(html).toContain(">Gemini<");
    expect(html).toContain(">Claude Opus 5.5<");
    for (const value of ["gemini", "opus"]) {
      expect(itemFor(value)["aria-disabled"]).toBeUndefined();
      expect(itemFor(value).disabled).toBeFalsy();
    }
  });
});

// 구성 흐름 원고 확인 창: 승인한 장면 구성안이 25턴이라 상한 20턴인 두 모델을 못 쓴다.
const MANUSCRIPT = toOutlineChapterModelOptions(
  [
    { id: "gemini", name: "Gemini", cost: 80, eligible: true, ineligibleReason: null, maxTurns: 45 },
    { id: "sonnet", name: "Claude Sonnet 5.5", cost: 180, eligible: false, ineligibleReason: "too_many_turns", maxTurns: 20 },
    { id: "opus", name: "Claude Opus 5.5", cost: 300, eligible: false, ineligibleReason: "too_many_turns", maxTurns: 20 },
  ],
  25,
);

describe("ChapterModelSelect — 원고 확인 창", () => {
  it("못 쓰는 모델의 항목 글(접근 이름)에 이유와 턴 수가 든다", () => {
    const html = render(MANUSCRIPT);
    expect(html).toContain("Claude Sonnet 5.5 · 대화가 길어 이 모델로는 못 써요 (25턴 · 20턴까지)");
    expect(html).toContain("Claude Opus 5.5 · 대화가 길어 이 모델로는 못 써요 (25턴 · 20턴까지)");
  });

  it("못 쓰는 모델이 골라져도 부모에게 알리지 않는다", () => {
    const picked: NovelChapterModelId[] = [];
    render(MANUSCRIPT, (id) => picked.push(id));
    captured.onValueChange?.("opus");
    expect(picked).toEqual([]);
  });
});
