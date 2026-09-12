import type { FieldErrors } from "react-hook-form";
import { describe, expect, it } from "vitest";

import type { BuilderTab } from "@/entities/content";

import { firstErrorLocation } from "./firstErrorLocation";

/** 픽스처가 참조하는 폼 경로만 담은 지역 타입. 실제 폼 타입(`features/build-story`의
 * `StoryBuilderFormValues`)을 쓰면 features끼리 import하는 셈이라(FSD-04,
 * fe-convention-refactor-goal-prompt.md R-1) 여기서 모양만 다시 적는다 — 검증 대상은 경로 매칭이지
 * 폼 스키마가 아니다. */
type StoryFormValuesFixture = {
  profile: { name: string; oneLiner: string };
  registration: { description: string };
  startingSetups: { endings: { name: string }[] }[];
  shortcuts: { name: string }[];
};

/** `features/build-story`의 `STORY_TABS`를 값 그대로 옮긴 픽스처(같은 이유로 import 대신 리터럴).
 * 탭 선언 순서 자체가 이 테스트의 검증 대상이라 목록을 줄이지 않는다. */
const STORY_TABS: readonly BuilderTab[] = [
  { id: "profile", label: "프로필", fields: ["profile"], preview: "card" },
  { id: "setting", label: "설정", fields: ["storySetting"], preview: "chat" },
  { id: "startingSetup", label: "시작설정", fields: ["startingSetups"], preview: "chat" },
  { id: "stat", label: "스탯", fields: ["startingSetups.*.stats"], preview: "chat" },
  { id: "keywordNote", label: "키워드북", fields: ["keywordNotes"], preview: "chat" },
  { id: "shortcut", label: "단축어", fields: ["shortcuts"], preview: "chat" },
  { id: "ending", label: "엔딩", fields: ["startingSetups.*.endings"], preview: "chat" },
  { id: "registration", label: "등록", fields: ["registration"], preview: "card" },
];

function fieldError(message = "필수 항목이에요."): { type: string; message: string } {
  return { type: "custom", message };
}

describe("firstErrorLocation", () => {
  it("에러가 없으면 undefined를 돌려준다", () => {
    const errors: FieldErrors<StoryFormValuesFixture> = {};

    expect(firstErrorLocation(errors, STORY_TABS)).toBeUndefined();
  });

  it("에러 객체에 담긴 키 순서가 아니라 STORY_TABS 선언 순서로 첫 탭을 고른다", () => {
    // registration을 profile보다 먼저 넣어도 STORY_TABS 선언 순서(profile이 1번째)가 이겨야 한다.
    const errors: FieldErrors<StoryFormValuesFixture> = {
      registration: { description: fieldError() },
      profile: { name: fieldError() },
    };

    expect(firstErrorLocation(errors, STORY_TABS)).toEqual({ tabId: "profile", fieldPath: "profile.name" });
  });

  it("스키마 키 선언 순서가 아니라 탭 선언 순서를 따른다 — startingSetups(스키마 3번째 키)의 ending 탭(탭 선언 7번째)보다 shortcuts(스키마 5번째 키, 탭 선언 6번째)가 먼저 온다", () => {
    const errors: FieldErrors<StoryFormValuesFixture> = {
      startingSetups: [{ endings: [{ name: fieldError() }] }],
      shortcuts: [{ name: fieldError() }],
    };

    expect(firstErrorLocation(errors, STORY_TABS)).toEqual({
      tabId: "shortcut",
      fieldPath: "shortcuts.0.name",
    });
  });

  it("같은 탭 안에 에러가 여럿이면 순회 순서상 먼저 나온 경로를 결정론적으로 고른다", () => {
    const errors: FieldErrors<StoryFormValuesFixture> = {
      profile: { oneLiner: fieldError(), name: fieldError() },
    };

    expect(firstErrorLocation(errors, STORY_TABS)).toEqual({
      tabId: "profile",
      fieldPath: "profile.oneLiner",
    });
  });
});
