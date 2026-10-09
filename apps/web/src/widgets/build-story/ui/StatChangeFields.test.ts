import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { createEmptyDraft } from "@/entities/content";
import {
  serverToForm,
  STAT_RULES_WITH_COUNTER_MESSAGE,
  type StatDefValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";

import { StatChangeFields } from "./StatChangeFields";
import { StatRuleList } from "./StatRuleList";

const RULE = { id: "rule-1", condition: "사용자가 약속을 지켰다", delta: 3 };

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
    rules: [],
    ...overrides,
  };
}

/** `perTurnDeltaError` 를 주면 발행 검증이 턴당 칸에 오류를 붙인 상태로 그린다. 턴당 칸과 규칙 목록을 함께 그린다. */
function render(value: StatDefValues, perTurnDeltaError?: string): string {
  function WithForm() {
    const draft = createEmptyDraft("story");
    if (draft.type !== "story") throw new Error("story draft expected");
    const values: StoryBuilderFormValues = serverToForm(draft);
    values.startingSetups = [
      { id: "s1", name: "", prologue: "", suggestedReplies: [], stats: [value], endings: [], situationNotes: [] },
    ];
    const errors =
      perTurnDeltaError === undefined
        ? undefined
        : { startingSetups: [{ stats: [{ perTurnDelta: { type: "custom", message: perTurnDeltaError } }] }] };
    const form = useForm<StoryBuilderFormValues>({ defaultValues: values, errors });
    const props = { id: "x", startingSetupIndex: 0, statIndex: 0, stat: value };
    return createElement(FormProvider<StoryBuilderFormValues>, {
      ...form,
      children: [createElement(StatChangeFields, { key: "a", ...props }), createElement(StatRuleList, { key: "b", ...props })],
    });
  }
  return renderToStaticMarkup(createElement(WithForm));
}

/** id 로 찾은 컨트롤 여는 태그. */
function controlTag(html: string, id: string): string {
  return new RegExp(`<[^>]*\\bid="${id}"[^>]*>`).exec(html)?.[0] ?? "";
}

/** 글자로 찾은 버튼 여는 태그. */
function buttonTag(html: string, label: string): string {
  return new RegExp(`<button[^>]*>(?:(?!</button>).)*${label}`).exec(html)?.[0] ?? "";
}

function isDisabled(html: string, id: string): boolean {
  return /\sdisabled=""/.test(controlTag(html, id));
}

function isAddLocked(html: string): boolean {
  return /aria-disabled="true"/.test(buttonTag(html, "규칙 추가"));
}

const PER_TURN = "stat-x-per-turn-delta";

describe("턴당 자동 변화와 규칙의 양쪽 잠금", () => {
  it("둘 다 비었으면 턴당 칸도 규칙 추가도 열려 있다", () => {
    const html = render(stat({}));
    expect(isDisabled(html, PER_TURN)).toBe(false);
    expect(isAddLocked(html)).toBe(false);
    expect(html).toContain("아직 규칙이 없어요.");
  });

  it("턴당 자동 변화가 있으면 규칙 추가를 잠그고 그 이유를 버튼에 잇는다", () => {
    const html = render(stat({ perTurnDelta: -1 }));
    expect(isDisabled(html, PER_TURN)).toBe(false);
    expect(isAddLocked(html)).toBe(true);
    expect(buttonTag(html, "규칙 추가")).toContain('aria-describedby="stat-x-rules-reason"');
    expect(html).toContain("턴당 자동 변화가 있는 스탯은 AI가 판정하지 않아 규칙을 쓰지 않아요.");
  });

  it("규칙이 있으면 턴당 칸을 잠그고 그 이유를 칸에 잇는다", () => {
    const html = render(stat({ rules: [RULE] }));
    expect(isDisabled(html, PER_TURN)).toBe(true);
    expect(controlTag(html, PER_TURN)).toContain('aria-describedby="stat-x-change-hint"');
    expect(html).toContain("규칙이 있으면 턴당 자동 변화는 쓰지 않아요.");
    expect(isAddLocked(html)).toBe(false);
  });

  it("둘 다 채워진 채 들어오면 어느 쪽도 잠그지 않고 한쪽을 비우라고 중립 톤으로 안내한다", () => {
    const html = render(stat({ perTurnDelta: -1, rules: [RULE] }));
    expect(isDisabled(html, PER_TURN)).toBe(false);
    expect(isAddLocked(html)).toBe(false);
    expect(controlTag(html, "stat-x-change-hint")).toContain("text-muted-foreground");
    expect(html).toContain("턴당 자동 변화와 규칙은 함께 쓸 수 없어요. 하나를 비워 주세요.");
    // 폼 검증 전에는 오류 문장이 없다 — 오류는 폼 상태에서만 온다(필수 별표의 빨강은 오류가 아니다).
    expect(html).not.toContain('role="alert"');
  });

  it("발행 검증이 턴당 칸에 붙인 오류는 그 아래에 그대로 보이고 칸에 이어진다", () => {
    const html = render(stat({ perTurnDelta: -1, rules: [RULE] }), STAT_RULES_WITH_COUNTER_MESSAGE);
    expect(controlTag(html, "stat-x-per-turn-delta-error")).toContain("text-destructive-text");
    expect(html).toContain(STAT_RULES_WITH_COUNTER_MESSAGE);
    expect(controlTag(html, PER_TURN)).toContain('aria-describedby="stat-x-change-hint stat-x-per-turn-delta-error"');
  });
});

describe("규칙 목록", () => {
  it("규칙 수를 세고, 증감은 부호를 붙여 보인다", () => {
    const html = render(stat({ rules: [RULE, { ...RULE, id: "rule-2", delta: -5 }] }));
    expect(html).toContain("규칙 2 / 10");
    expect(html).toContain('value="+3"');
    expect(html).toContain('value="-5"');
    expect(html).toContain('aria-label="2번째 규칙 순서 변경"');
    expect(html).toContain('aria-label="2번째 규칙 삭제"');
  });

  it("10개면 추가를 잠그고 상한 사유를 잇는다", () => {
    const rules = Array.from({ length: 10 }, (_, index) => ({ ...RULE, id: `rule-${index}` }));
    const html = render(stat({ rules }));
    expect(isAddLocked(html)).toBe(true);
    expect(html).toContain("규칙은 스탯마다 10개까지예요.");
  });

  it("범위 폭을 넘는 증감은 저장을 막지 않는 안내로 미리 알린다", () => {
    const html = render(stat({ rules: [{ ...RULE, delta: -50 }] }));
    expect(html).toContain("이 스탯의 범위 폭(42)보다 커서 발행할 수 없어요.");
    expect(html).not.toContain('role="alert"');
  });
});
