import { createFormControl, get } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { createEmptyDraft } from "@/entities/content";
import { serverToForm, type StatDefValues, type StoryBuilderFormValues } from "@/features/build-story";

import { perTurnDeltaFromInput } from "./perTurnDelta";

// 스탯 탭이 칸을 등록할 때와 같은 옵션.
const perTurnDeltaOptions = { setValueAs: perTurnDeltaFromInput };

const STATS = "startingSetups.0.stats" as const;

function stat(id: string, perTurnDelta: number | null): StatDefValues {
  return { id, name: id, icon: "Heart", color: "c", min: 0, max: 100, initial: 0, description: "d", perTurnDelta };
}

/** 초안을 불러온 순간의 스탯이 `defaultValues` 로 굳은 폼. */
function createForm(loadedStats: StatDefValues[]) {
  const draft = createEmptyDraft("story");
  if (draft.type !== "story") throw new Error("story draft expected");
  const values: StoryBuilderFormValues = serverToForm(draft);
  values.startingSetups = [{ id: "s1", name: "", prologue: "", suggestedReplies: [], stats: loadedStats, endings: [] }];
  return createFormControl<StoryBuilderFormValues>({ defaultValues: values });
}

/** 입력칸이 화면에 붙는 순간(마운트)을 흉내 낸다. 폼은 이때 칸 값을 정한다. */
function mountPerTurnInput(form: ReturnType<typeof createForm>, statIndex: number) {
  const input = { name: `${STATS}.${statIndex}.perTurnDelta`, type: "number", value: "" };
  form.register(`${STATS}.${statIndex}.perTurnDelta`, perTurnDeltaOptions).ref(input);
}

// 훅 밖의 폼은 마운트된 적이 없어 `getValues` 가 `defaultValues` 를 돌려준다 — 컨트롤이 쥔 현재 값을 직접 읽는다.
function perTurnDeltaAt(form: ReturnType<typeof createForm>, statIndex: number): unknown {
  return get(form.control._formValues, `${STATS}.${statIndex}.perTurnDelta`);
}

describe("턴당 자동 변화 칸은 불러올 때의 같은 자리 값을 물려받지 않는다", () => {
  it("지운 스탯 자리에 새로 추가한 스탯의 칸은 빈 채로 붙는다", () => {
    const form = createForm([stat("a", null), stat("b", -3)]);
    form.setValue(STATS, [stat("a", null)]);
    form.setValue(STATS, [stat("a", null), stat("new", null)]);

    mountPerTurnInput(form, 1);

    expect(perTurnDeltaAt(form, 1)).toBeNull();
  });

  it("비운 칸은 탭을 오가며 다시 붙어도 불러올 때의 값으로 되살아나지 않는다", () => {
    const form = createForm([stat("a", -3)]);
    form.setValue(`${STATS}.0.perTurnDelta`, perTurnDeltaFromInput(""));

    mountPerTurnInput(form, 0);

    expect(perTurnDeltaAt(form, 0)).toBeNull();
  });
});
