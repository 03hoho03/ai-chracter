import { zodResolver } from "@hookform/resolvers/zod";
import { createFormControl, type Resolver } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { createEmptyDraft } from "@/entities/content";
import {
  serverToForm,
  storyBuilderSchema,
  type StatDefValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";

import { revalidateStatRange, revalidateStatRangeIfInvalid } from "./statRangeValidation";

function stat(id: string, overrides: Partial<StatDefValues> = {}): StatDefValues {
  // 설명을 비워 둔다 — 범위 밖 칸의 오류가 이 검사로 새어 나오지 않는지 보려고.
  return { id, name: id, icon: "", color: "", min: 0, max: 100, initial: 0, description: "", perTurnDelta: null, rules: [], ...overrides };
}

/** 셸과 같은 리졸버를 단 폼. 초안은 이름·시작설정 도입부 등이 비어 폼 전체로는 오류투성이다. */
function createForm(stats: StatDefValues[]) {
  const draft = createEmptyDraft("story");
  if (draft.type !== "story") throw new Error("story draft expected");
  const values = serverToForm(draft);
  values.startingSetups = [
    { id: "s1", name: "", prologue: "", suggestedReplies: [], stats, endings: [], situationNotes: [] },
  ];
  // 셸과 같은 단언 — zod `.default()` 때문에 리졸버의 입력·출력 타입이 갈린다.
  const resolver = zodResolver(storyBuilderSchema) as Resolver<StoryBuilderFormValues>;
  return createFormControl<StoryBuilderFormValues>({ resolver, defaultValues: values });
}

function errorPaths(form: ReturnType<typeof createForm>): string[] {
  const paths: string[] = [];
  function walk(node: unknown, prefix: string) {
    if (node === null || typeof node !== "object") return;
    if ("message" in node && "type" in node) {
      paths.push(prefix);
      return;
    }
    for (const [key, child] of Object.entries(node)) walk(child, prefix ? `${prefix}.${key}` : key);
  }
  // 훅 밖의 폼이라 `formState` 프록시가 없다 — 컨트롤이 쥔 오류 객체를 그대로 읽는다.
  walk(form.control._formState.errors, "");
  return paths;
}

describe("revalidateStatRange", () => {
  it("그 스탯의 범위 칸에만 오류를 붙인다 — 같은 스탯의 빈 설명·다른 스탯·폼의 다른 칸은 건드리지 않는다", async () => {
    const form = createForm([stat("a", { min: 100, max: 0 }), stat("b", { initial: 500 })]);

    await revalidateStatRange(form, "startingSetups.0.stats.0");

    expect(errorPaths(form)).toEqual(["startingSetups.0.stats.0.max"]);
    expect(form.getFieldState("startingSetups.0.stats.0.max").error?.message).toBe("최대값은 최소값보다 커야 해요");
  });

  it("초기값이 범위 밖이면 초기값 칸에 붙는다(같은 스탯의 다른 칸이 비어 있어도 범위 검사가 돈다)", async () => {
    const form = createForm([stat("a", { initial: 500 })]);

    await revalidateStatRange(form, "startingSetups.0.stats.0");

    expect(errorPaths(form)).toEqual(["startingSetups.0.stats.0.initial"]);
  });

  it("고치면 다시 검사해 오류를 지운다", async () => {
    const form = createForm([stat("a", { initial: 500 })]);
    await revalidateStatRange(form, "startingSetups.0.stats.0");

    form.setValue("startingSetups.0.stats.0.max", 1000);
    await revalidateStatRangeIfInvalid(form, "startingSetups.0.stats.0");

    expect(errorPaths(form)).toEqual([]);
  });

  it("최대값을 고쳐도 초기값 칸의 오류까지 함께 풀린다(세 칸을 함께 본다)", async () => {
    const form = createForm([stat("a", { min: 100, max: 0, initial: 50 })]);
    await revalidateStatRange(form, "startingSetups.0.stats.0");
    expect(errorPaths(form)).toEqual(["startingSetups.0.stats.0.max"]);

    // 최대값만 고치면 이제 초기값(50)이 100~200 밖이다 — 초기값 칸으로 옮겨 간다.
    form.setValue("startingSetups.0.stats.0.max", 200);
    await revalidateStatRangeIfInvalid(form, "startingSetups.0.stats.0");

    expect(errorPaths(form)).toEqual(["startingSetups.0.stats.0.initial"]);
  });

  it("빈 칸·소수는 그 칸에 한국어 문구로 붙는다", async () => {
    const form = createForm([stat("a", { min: Number.NaN, initial: 1.5 })]);

    await revalidateStatRange(form, "startingSetups.0.stats.0");

    expect(form.getFieldState("startingSetups.0.stats.0.min").error?.message).toBe("최소값을 입력해주세요");
    expect(form.getFieldState("startingSetups.0.stats.0.initial").error?.message).toBe("정수로 입력해주세요");
  });
});

describe("revalidateStatRangeIfInvalid", () => {
  it("오류가 떠 있지 않으면 검사하지 않는다 — 입력 중인 칸에 새 오류를 띄우지 않는다", async () => {
    const form = createForm([stat("a", { min: 100, max: 0 })]);

    expect(revalidateStatRangeIfInvalid(form, "startingSetups.0.stats.0")).toBeUndefined();
    await Promise.resolve();

    expect(errorPaths(form)).toEqual([]);
  });
});
