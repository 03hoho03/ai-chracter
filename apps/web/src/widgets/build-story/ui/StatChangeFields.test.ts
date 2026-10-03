import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { createEmptyDraft } from "@/entities/content";
import { serverToForm, type StatDefValues, type StoryBuilderFormValues } from "@/features/build-story";

import { StatChangeFields } from "./StatChangeFields";

function stat(overrides: Partial<StatDefValues>): StatDefValues {
  return {
    id: "stat-1",
    name: "상영회까지",
    icon: "Heart",
    color: "c",
    min: 0,
    max: 42,
    initial: 42,
    description: "d",
    perTurnDelta: null,
    changeDirection: "both",
    maxChangePerTurn: null,
    ...overrides,
  };
}

function render(value: StatDefValues): string {
  function WithForm() {
    const draft = createEmptyDraft("story");
    if (draft.type !== "story") throw new Error("story draft expected");
    const values: StoryBuilderFormValues = serverToForm(draft);
    values.startingSetups = [
      { id: "s1", name: "", prologue: "", suggestedReplies: [], stats: [value], endings: [], situationNotes: [] },
    ];
    const form = useForm<StoryBuilderFormValues>({ defaultValues: values });
    return createElement(FormProvider<StoryBuilderFormValues>, {
      ...form,
      children: createElement(StatChangeFields, { id: "x", startingSetupIndex: 0, statIndex: 0, stat: value }),
    });
  }
  return renderToStaticMarkup(createElement(WithForm));
}

/** id 로 찾은 컨트롤 여는 태그. */
function controlTag(html: string, id: string): string {
  return new RegExp(`<[^>]*\\bid="${id}"[^>]*>`).exec(html)?.[0] ?? "";
}

function isDisabled(html: string, id: string): boolean {
  return /\sdisabled=""/.test(controlTag(html, id));
}

const PER_TURN = "stat-x-per-turn-delta";
const DIRECTION = "stat-x-change-direction";
const MAX_CHANGE = "stat-x-max-change";

describe("StatChangeFields 양쪽 잠금", () => {
  it("둘 다 비었으면 세 칸 모두 열려 있다", () => {
    const html = render(stat({}));
    expect([PER_TURN, DIRECTION, MAX_CHANGE].map((id) => isDisabled(html, id))).toEqual([false, false, false]);
  });

  it("턴당 자동 변화가 있으면 방향·폭을 잠그고 그 이유를 칸에 잇는다", () => {
    const html = render(stat({ perTurnDelta: -1 }));
    expect([PER_TURN, DIRECTION, MAX_CHANGE].map((id) => isDisabled(html, id))).toEqual([false, true, true]);
    expect(controlTag(html, MAX_CHANGE)).toContain('aria-describedby="stat-x-change-hint"');
    expect(html).toContain("턴당 자동 변화가 있으면 AI가 이 스탯을 바꾸지 않아서");
  });

  it("방향이나 폭을 걸면 턴당 자동 변화를 잠그고 그 이유를 칸에 잇는다", () => {
    const html = render(stat({ changeDirection: "decrease", maxChangePerTurn: 7 }));
    expect([PER_TURN, DIRECTION, MAX_CHANGE].map((id) => isDisabled(html, id))).toEqual([true, false, false]);
    expect(controlTag(html, PER_TURN)).toContain('aria-describedby="stat-x-change-hint"');
    expect(html).toContain("AI가 정한 값이 이 방향과 폭을 넘으면 시스템이 잘라요.");
  });

  it("둘 다 채워진 채 들어오면 어느 쪽도 잠그지 않고 한쪽을 비우라고 오류 톤으로 알린다", () => {
    const html = render(stat({ perTurnDelta: -1, changeDirection: "decrease" }));
    expect([PER_TURN, DIRECTION, MAX_CHANGE].map((id) => isDisabled(html, id))).toEqual([false, false, false]);
    expect(controlTag(html, "stat-x-change-hint")).toContain("text-destructive-text");
    expect(html).toContain("함께 쓸 수 없어요. 한쪽을 비워 주세요.");
  });
});
