import { set, type FieldErrors } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { createEmptyDraft } from "@/entities/content";
import { errorItemKeys, errorParentItemId, firstErrorLocation, itemOpenKey } from "@/features/build-common";
import {
  serverToForm,
  situationNoteStatNotFoundPaths,
  STARTING_SETUP_SCOPE,
  STORY_COLLAPSIBLE_LISTS,
  STORY_TABS,
  type StoryBuilderFormValues,
} from "@/features/build-story";
import { ApiErrorObject } from "@/shared/api/client";

function formValues(): StoryBuilderFormValues {
  const draft = createEmptyDraft("story");
  if (draft.type !== "story") throw new Error("story draft expected");
  const values = serverToForm(draft);
  const rule = { kind: "rule", id: "r-gone", statId: "gone", operator: "<=", value: 0, nextOp: null } as const;
  values.startingSetups = [
    { id: "setup-a", name: "봄", prologue: "p", suggestedReplies: [], stats: [], endings: [], situationNotes: [] },
    {
      id: "setup-b",
      name: "가을",
      prologue: "p",
      suggestedReplies: [],
      stats: [],
      endings: [],
      situationNotes: [
        { id: "note-1", name: "", content: "사실", conditionRules: [] },
        {
          id: "note-2",
          name: "",
          content: "사실",
          conditionRules: [{ kind: "group", id: "group-1", nextOp: null, rules: [rule] }],
        },
      ],
    },
  ];
  return values;
}

/** 셸이 하는 것처럼 저장 거절의 경로마다 `setError` 를 건 뒤의 오류 객체. */
function errorsFor(paths: readonly string[]): FieldErrors<StoryBuilderFormValues> {
  const errors: FieldErrors<StoryBuilderFormValues> = {};
  for (const path of paths) set(errors, path, { type: "server", message: "m" });
  return errors;
}

// 저장 거절이 가리킨 조건 줄까지 셸이 데려가는지 — 탭 전환, 고른 시작설정, 노트·그룹 펼침, 포커스 경로를 한 번에 본다. 하나라도
// 어긋나면 작가는 상황 노트 탭에 와도 그 조건이 접힌 노트 안에 숨어 있거나 다른 시작설정의 목록을 보게 된다.
describe("상황 노트 저장 거절의 오류 위치", () => {
  const values = formValues();
  const [path] =
    situationNoteStatNotFoundPaths(
      new ApiErrorObject({
        status: 422,
        message: "x",
        detail: {
          code: "SITUATION_NOTE_STAT_NOT_FOUND",
          paths: ["startingSetups[1].situationNotes[1].conditionRules[0].rules[0].statId"],
        },
      }),
    ) ?? [];
  const errors = errorsFor(path === undefined ? [] : [path]);
  const location = firstErrorLocation(errors, STORY_TABS);

  it("상황 노트 탭으로 가서 그 조건 줄의 스탯 칸을 포커스 대상으로 삼는다", () => {
    expect(location).toEqual({
      tabId: "situationNote",
      fieldPath: "startingSetups.1.situationNotes.1.conditionRules.0.rules.0.statId",
    });
  });

  it("그 노트와 노트 안 규칙 그룹을 펼치고, 시작설정 카드는 펼치지 않는다", () => {
    const keys = errorItemKeys(errors, values, STORY_COLLAPSIBLE_LISTS, STORY_TABS);

    expect(keys).toContain(itemOpenKey("situationNote", "note-2"));
    expect(keys).toContain(itemOpenKey("situationNoteRuleGroup", "group-1"));
    expect(keys).not.toContain(itemOpenKey("startingSetup", "setup-b"));
  });

  it("상황 노트 탭이 그 시작설정을 보이게 고른다", () => {
    expect(errorParentItemId(errors, values, STARTING_SETUP_SCOPE, STORY_TABS, location?.fieldPath)).toBe("setup-b");
  });

  it("발행 전 폼 검증의 조건 없음 오류도 같은 노트를 펼치고 조건 칸을 포커스 대상으로 삼는다", () => {
    const emptyErrors = errorsFor(["startingSetups.1.situationNotes.0.conditionRules"]);

    expect(firstErrorLocation(emptyErrors, STORY_TABS)?.tabId).toBe("situationNote");
    expect(errorItemKeys(emptyErrors, values, STORY_COLLAPSIBLE_LISTS, STORY_TABS)).toContain(
      itemOpenKey("situationNote", "note-1"),
    );
  });
});
