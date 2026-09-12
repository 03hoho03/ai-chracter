import type { FieldErrors } from "react-hook-form";
import { describe, expect, it } from "vitest";

import type { BuilderTab } from "@/entities/content";

import { errorTabs } from "./errorTabs";

/** 픽스처가 참조하는 폼 경로만 담은 지역 타입. 실제 폼 타입(`features/build-story`의
 * `StoryBuilderFormValues`)을 쓰면 features끼리 import하는 셈이라(FSD-04,
 * fe-convention-refactor-goal-prompt.md R-1) 여기서 모양만 다시 적는다 — 검증 대상은 경로 매칭이지
 * 폼 스키마가 아니다. */
type StoryFormValuesFixture = {
  profile: { name: string };
  startingSetups: { name: string; stats: { name: string }[] }[];
  shortcuts: { name: string }[];
};

/** `features/build-story`의 `STORY_TABS`를 값 그대로 옮긴 픽스처(같은 이유로 import 대신 리터럴).
 * 겹치는 프리픽스(`startingSetups` ↔ `startingSetups.*.stats`)와 탭 선언 순서가 이 테스트의 검증
 * 대상이라 목록을 줄이지 않는다. */
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

describe("errorTabs", () => {
  it("startingSetups.0.stats.1.name처럼 겹치는 경로는 더 구체적인 stat 탭에만 귀속된다", () => {
    const errors: FieldErrors<StoryFormValuesFixture> = {
      startingSetups: [
        undefined,
        { stats: [undefined, { name: fieldError() }] },
      ],
    };

    expect(errorTabs(errors, STORY_TABS)).toEqual(new Set(["stat"]));
  });

  it("최상위 키 에러(profile.name)는 profile 탭에 귀속된다", () => {
    const errors: FieldErrors<StoryFormValuesFixture> = { profile: { name: fieldError() } };

    expect(errorTabs(errors, STORY_TABS)).toEqual(new Set(["profile"]));
  });

  it("빈 에러는 빈 집합을 돌려준다", () => {
    const errors: FieldErrors<StoryFormValuesFixture> = {};

    expect(errorTabs(errors, STORY_TABS)).toEqual(new Set());
  });

  it("배열 인덱스 구멍(에러 없는 자리)은 건너뛰고 나머지만 매칭한다", () => {
    const errors: FieldErrors<StoryFormValuesFixture> = {
      startingSetups: [undefined, { name: fieldError() }],
    };

    expect(errorTabs(errors, STORY_TABS)).toEqual(new Set(["startingSetup"]));
  });

  it("서로 다른 탭에 걸친 에러는 둘 다 담는다", () => {
    const errors: FieldErrors<StoryFormValuesFixture> = {
      profile: { name: fieldError() },
      shortcuts: [{ name: fieldError() }],
    };

    expect(errorTabs(errors, STORY_TABS)).toEqual(new Set(["profile", "shortcut"]));
  });

  // RHF의 FieldErrors 타입(`Merge<FieldError, FieldErrorsImpl<T[K]>>`)은 배열 필드마다 `root?:
  // FieldError`를 둔다 — 아이템이 이미 마운트돼 있어 인덱스별 에러(`shortcuts.0.name`)도 함께
  // 존재하는 상태에서 배열 자체의 min(1) 등이 깨지면 그 에러는 `shortcuts.root`에 담긴다(인덱스
  // 자리를 차지할 수 없어서). `matchesPrefix`가 프리픽스 길이만 비교하므로 이미 옳게 동작하지만
  // (A-1), 회귀를 막기 위해 고정해 둔다.
  it("배열 자체 에러(root)는 인덱스 에러와 같은 탭에 귀속된다", () => {
    const shortcutsErrors = Object.assign([{ name: fieldError() }], {
      root: fieldError("최소 1개 이상 입력해주세요."),
    });
    const errors: FieldErrors<StoryFormValuesFixture> = { shortcuts: shortcutsErrors };

    expect(errorTabs(errors, STORY_TABS)).toEqual(new Set(["shortcut"]));
  });

  // RHF의 `setError(path, {message})`는 `type`을 채우지 않는다 — 내부 `setError`가 호출자가 준
  // 객체만 스프레드해서 `{message, ref}`를 만든다(`fieldError()` 헬퍼는 항상 `type: "custom"`을
  // 넣으므로 이 모양을 못 만든다 — 직접 구성한다). `isFieldErrorLeaf`가 `type`에만 의존하면 이
  // 자리가 잎으로 판정되지 않아 `flattenFieldErrorPaths`가 통째로 놓치고 `errorTabs`가 빈
  // 집합을 돌려준다(StoryBuilderShell의 서버 거부 경로에서 실제로 발생).
  it("setError가 만드는 type 없는 에러도 잎으로 인식돼 올바른 탭에 귀속된다", () => {
    const errors = {
      profile: { name: { message: "필수 항목이에요.", ref: undefined } },
    } as FieldErrors<StoryFormValuesFixture>;

    expect(errorTabs(errors, STORY_TABS)).toEqual(new Set(["profile"]));
  });
});
