import type { FieldErrors } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { STORY_TABS, type StoryBuilderFormValues } from "@/features/build-story";

import { firstErrorLocation } from "./firstErrorLocation";

function fieldError(message = "필수 항목이에요."): { type: string; message: string } {
  return { type: "custom", message };
}

describe("firstErrorLocation", () => {
  it("에러가 없으면 null을 돌려준다", () => {
    const errors: FieldErrors<StoryBuilderFormValues> = {};

    expect(firstErrorLocation(errors, STORY_TABS)).toBeNull();
  });

  it("에러 객체에 담긴 키 순서가 아니라 STORY_TABS 선언 순서로 첫 탭을 고른다", () => {
    // registration을 profile보다 먼저 넣어도 STORY_TABS 선언 순서(profile이 1번째)가 이겨야 한다.
    const errors = {
      registration: { description: fieldError() },
      profile: { name: fieldError() },
    } as FieldErrors<StoryBuilderFormValues>;

    expect(firstErrorLocation(errors, STORY_TABS)).toEqual({ tabId: "profile", fieldPath: "profile.name" });
  });

  it("스키마 키 선언 순서가 아니라 탭 선언 순서를 따른다 — startingSetups(스키마 3번째 키)의 ending 탭(탭 선언 7번째)보다 shortcuts(스키마 5번째 키, 탭 선언 6번째)가 먼저 온다", () => {
    const errors = {
      startingSetups: [{ endings: [{ name: fieldError() }] }],
      shortcuts: [{ name: fieldError() }],
    } as FieldErrors<StoryBuilderFormValues>;

    expect(firstErrorLocation(errors, STORY_TABS)).toEqual({
      tabId: "shortcut",
      fieldPath: "shortcuts.0.name",
    });
  });

  it("같은 탭 안에 에러가 여럿이면 순회 순서상 먼저 나온 경로를 결정론적으로 고른다", () => {
    const errors = {
      profile: { oneLiner: fieldError(), name: fieldError() },
    } as FieldErrors<StoryBuilderFormValues>;

    expect(firstErrorLocation(errors, STORY_TABS)).toEqual({
      tabId: "profile",
      fieldPath: "profile.oneLiner",
    });
  });
});
