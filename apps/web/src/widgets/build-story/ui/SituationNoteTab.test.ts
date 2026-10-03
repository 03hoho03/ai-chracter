import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { createEmptyDraft, type StoryDraftContent } from "@/entities/content";
import {
  formToServer,
  MAX_SITUATION_NOTES,
  removeRuleListItem,
  serverToForm,
  type SingleRuleValues,
  type SituationNoteValues,
  type StartingSetupValues,
  type StatDefValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";

import { SituationNoteTab } from "./SituationNoteTab";

const STAT: StatDefValues = {
  id: "days",
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
};

function rule(id: string, statId = "days"): SingleRuleValues {
  return { kind: "rule", id, statId, operator: "<=", value: 0, nextOp: null };
}

function note(id: string, overrides: Partial<SituationNoteValues> = {}): SituationNoteValues {
  return { id, name: "", content: "오늘은 상영회 당일이다.", conditionRules: [rule(`${id}-r`)], ...overrides };
}

function storyDraft(): Extract<StoryDraftContent, { type: "story" }> {
  const draft = createEmptyDraft("story");
  if (draft.type !== "story") throw new Error("story draft expected");
  return draft;
}

function setup(overrides: Partial<StartingSetupValues>): StartingSetupValues {
  return {
    id: "setup-1",
    name: "가을 학기",
    prologue: "p",
    suggestedReplies: [],
    stats: [STAT],
    endings: [],
    situationNotes: [],
    ...overrides,
  };
}

function renderWith(values: StoryBuilderFormValues): string {
  function WithForm() {
    const form = useForm<StoryBuilderFormValues>({ defaultValues: values });
    return createElement(FormProvider<StoryBuilderFormValues>, { ...form, children: createElement(SituationNoteTab) });
  }
  return renderToStaticMarkup(createElement(WithForm));
}

function render(setups: StartingSetupValues[]): string {
  const values = serverToForm(storyDraft());
  values.startingSetups = setups;
  return renderWith(values);
}

/** id 로 찾은 요소의 여는 태그. */
function tagWithId(html: string, id: string): string {
  return new RegExp(`<[^>]*\\bid="${id}"[^>]*>`).exec(html)?.[0] ?? "";
}

describe("SituationNoteTab 머리", () => {
  // "상황 노트"는 받침 없이 끝나 "은"을 붙이면 "상황 노트은"이 된다.
  it("시작설정이 하나면 칩 대신 문장으로 알리고 조사가 맞다", () => {
    const html = render([setup({})]);

    expect(html).toContain("‘가을 학기’의 상황 노트");
    expect(html).toContain("상황 노트는 시작설정마다 따로 정해요.");
    expect(html).not.toContain("상황 노트은");
    expect(html).not.toContain('role="radio"');
  });

  it("조건을 따지는 시점(보낸 순간의 게이지 값, 엔딩 규칙보다 한 턴 앞)을 머리에서 알린다", () => {
    const html = render([setup({})]);

    expect(html).toContain("사용자가 메시지를 보낸 순간의 게이지 값");
    expect(html).toContain("엔딩 규칙보다 한 턴");
  });

  it("시작설정이 없으면 시작설정부터 만들라고 안내한다", () => {
    expect(render([])).toContain("먼저 시작설정 탭에서 시작설정을 추가해주세요.");
  });
});

describe("SituationNoteTab 노트 추가 잠금", () => {
  it("노트가 10개면 추가 버튼을 aria-disabled 로 잠그고 사유를 잇는다", () => {
    const html = render([
      setup({ situationNotes: Array.from({ length: MAX_SITUATION_NOTES }, (_, index) => note(`n${index}`)) }),
    ]);
    const button = tagWithId(html, "situation-note-add");

    expect(html).toContain(`노트 ${MAX_SITUATION_NOTES} / ${MAX_SITUATION_NOTES}`);
    expect(button).toContain('aria-disabled="true"');
    // `disabled` 면 포커스가 body 로 떨어지고 사유가 키보드에 닿지 않는다.
    expect(button).not.toMatch(/\sdisabled=""/);
    expect(button).toContain('aria-describedby="situation-note-add-reason"');
    expect(tagWithId(html, "situation-note-add-reason")).not.toBe("");
    expect(html).toContain("노트는 시작설정마다 10개까지예요.");
  });

  it("9개면 잠그지 않는다", () => {
    const html = render([setup({ situationNotes: Array.from({ length: 9 }, (_, index) => note(`n${index}`)) })]);

    expect(tagWithId(html, "situation-note-add")).not.toContain('aria-disabled="true"');
  });

  it("스탯이 없으면 빈 상태가 이유를 말하고 추가 버튼이 그 문장을 사유로 가리킨다", () => {
    const html = render([setup({ stats: [] })]);

    expect(html).toContain("이 시작설정에는 아직 스탯이 없어요.");
    expect(tagWithId(html, "situation-note-add")).toContain('aria-disabled="true"');
    expect(tagWithId(html, "situation-note-add-reason")).toContain("<p");
  });

  it("스탯이 있고 노트가 없으면 빈 상태가 쓰는 법을 예로 보인다", () => {
    const html = render([setup({})]);

    expect(html).toContain("아직 상황 노트가 없어요.");
    expect(html).toContain("상영회까지 &lt;= 0");
    expect(tagWithId(html, "situation-note-add")).not.toContain('aria-disabled="true"');
  });
});

describe("SituationNoteCard", () => {
  // 자동저장은 폼 검증을 거치지 않아 상한을 넘는 글이 폼에 들어가면 서버가 초안 저장을 통째로 거절한다 — 입력 칸이 막는다.
  it("이름 20자·상황 800자를 입력 칸에서 막는다", () => {
    const html = render([setup({ situationNotes: [note("n1")] })]);

    expect(html).toMatch(/<input[^>]*maxLength="20"[^>]*name="startingSetups\.0\.situationNotes\.0\.name"/);
    expect(html).toMatch(/<textarea[^>]*maxLength="800"[^>]*name="startingSetups\.0\.situationNotes\.0\.content"/);
  });

  it("접힌 머리 줄에 이름(없으면 상황의 첫 줄)과 조건 요약을 보인다", () => {
    const html = render([
      setup({ situationNotes: [note("n1", { name: "상영회 당일" }), note("n2", { content: "첫 줄\n둘째 줄" })] }),
    ]);

    expect(html).toContain("상영회 당일");
    expect(html).toContain("첫 줄");
    expect(html).toContain("상영회까지 &lt;= 0");
    expect(html).toContain('aria-label="상영회 당일 상황 노트 삭제"');
    expect(html).toContain('aria-label="2번째 상황 노트 삭제"');
  });

  it("조건 칸은 필수 표시와 조건 수 / 상한을 보인다", () => {
    const html = render([setup({ situationNotes: [note("n1")] })]);

    expect(html).toContain("조건 1 / 10");
  });

  it("조건이 10개면 조건 추가 버튼을 잠그고 사유를 잇는다", () => {
    const html = render([
      setup({
        situationNotes: [note("n1", { conditionRules: Array.from({ length: 10 }, (_, index) => rule(`r${index}`)) })],
      }),
    ]);

    expect(html).toContain("조건은 노트마다 10개까지예요(그룹 안 조건 포함).");
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*>단일 규칙 추가/);
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*>규칙 그룹 추가/);
  });

  it("조건 줄의 스탯 칸에 폼 경로 표식이 붙어 발행 실패 때 셸이 그 칸을 찾는다", () => {
    const html = render([setup({ situationNotes: [note("n1")] })]);

    expect(html).toContain('data-field-path="startingSetups.0.situationNotes.0.conditionRules.0.statId"');
  });
});

// 다른 기기·이전 화면이 남긴 고아 조건이 든 초안을 열면 첫 자동저장부터 서버가 거절한다. 그 조건이 보이고 지워져야 막다른 길이 아니다.
describe("지워진 스탯을 쓰는 상황 노트 조건", () => {
  const draft = storyDraft();
  draft.startingSetups = [
    {
      id: "setup-1",
      name: "가을 학기",
      prologue: "p",
      openingMessage: null,
      playguide: null,
      suggestedReplies: [],
      statDefs: [],
      endings: [],
      situationNotes: [
        {
          id: "n1",
          name: "",
          infoText: "오늘은 상영회 당일이다.",
          conditionRules: [
            { kind: "rule", id: "r-gone", statId: "11111111-1111-4111-8111-111111111111", operator: "lte", threshold: 0, nextOp: null },
          ],
        },
      ],
    },
  ];
  const values = serverToForm(draft);

  it("응답으로 만든 폼에서 그 조건이 '지워진 스탯'으로 보이고 머리 줄에 경고가 뜬다", () => {
    const html = renderWith(values);

    expect(html).toContain("지워진 스탯 &lt;= 0");
    expect(html).toContain('aria-label="스탯 선택: 지워진 스탯"');
    expect(html).toContain("입력 오류가 있어요");
  });

  it("그 조건을 지우면 다음 저장 본문에서 빠진다", () => {
    const [setupValues] = values.startingSetups;
    const [noteValues] = setupValues?.situationNotes ?? [];
    if (!setupValues || !noteValues) throw new Error("fixture");
    noteValues.conditionRules = removeRuleListItem(noteValues.conditionRules, "r-gone");

    const [sentSetup] = formToServer(values).startingSetups;
    expect(sentSetup?.situationNotes?.[0]?.conditionRules).toEqual([]);
  });
});
