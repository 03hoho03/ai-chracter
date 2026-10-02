import type { FieldErrors } from "react-hook-form";
import { describe, expect, it } from "vitest";

import type { BuilderTab } from "@/entities/content";

import { errorParentItemId, type ErrorParentScope } from "./errorParentItemId";

/** `features/build-story` 의 `STORY_TABS`·`STARTING_SETUP_SCOPE` 를 값 그대로 옮긴 픽스처(features 슬라이스끼리
 * import 하지 않는다). 탭 순서(스탯이 엔딩보다 앞)가 검증 대상이다. */
const STORY_TABS: readonly BuilderTab[] = [
  { id: "profile", label: "프로필", fields: ["profile"], preview: "card" },
  { id: "startingSetup", label: "시작설정", fields: ["startingSetups"], preview: "chat" },
  { id: "stat", label: "스탯", fields: ["startingSetups.*.stats"], preview: "chat" },
  { id: "ending", label: "엔딩", fields: ["startingSetups.*.endings"], preview: "chat" },
];
const SCOPE: ErrorParentScope = { path: "startingSetups", tabIds: ["stat", "ending"] };

/** 픽스처가 쓰는 폼 경로만 담은 지역 타입. */
type StoryFixture = {
  profile: { name: string };
  startingSetups: { id: string; name?: string; stats: { id: string; name?: string }[]; endings: { id: string; name?: string }[] }[];
};

const VALUES: StoryFixture = {
  profile: { name: "" },
  startingSetups: [
    { id: "setup-a", stats: [{ id: "s" }], endings: [{ id: "e" }] },
    { id: "setup-b", stats: [{ id: "s2" }], endings: [{ id: "e2" }] },
  ],
};

function fieldError(): { type: string; message: string } {
  return { type: "custom", message: "필수 항목이에요." };
}

function pick(errors: FieldErrors<StoryFixture>, focusPath: string | undefined): string | undefined {
  return errorParentItemId(errors, VALUES, SCOPE, STORY_TABS, focusPath);
}

describe("errorParentItemId", () => {
  it("포커스 경로가 스탯이면 그 경로의 시작설정을 고른다", () => {
    const errors: FieldErrors<StoryFixture> = { startingSetups: [undefined, { stats: [{ name: fieldError() }] }] };
    expect(pick(errors, "startingSetups.1.stats.0.name")).toBe("setup-b");
  });

  it("포커스 경로가 다른 탭이면 스탯·엔딩 오류 중 탭 순서상 첫 것의 시작설정을 고른다", () => {
    const errors: FieldErrors<StoryFixture> = {
      profile: { name: fieldError() },
      startingSetups: [{ endings: [{ name: fieldError() }] }, { stats: [{ name: fieldError() }] }],
    };
    expect(pick(errors, "profile.name")).toBe("setup-b");
  });

  it("포커스 경로가 엔딩이면 앞 시작설정의 스탯 오류보다 포커스 경로가 이긴다", () => {
    const errors: FieldErrors<StoryFixture> = {
      startingSetups: [{ stats: [{ name: fieldError() }] }, { endings: [{ name: fieldError() }] }],
    };
    expect(pick(errors, "startingSetups.1.endings.0.name")).toBe("setup-b");
  });

  it("시작설정 아래 목록 자리 오류도 그 시작설정을 고른다", () => {
    const errors: FieldErrors<StoryFixture> = { startingSetups: [undefined, { endings: fieldError() }] };
    expect(pick(errors, "startingSetups.1.endings")).toBe("setup-b");
    expect(pick(errors, undefined)).toBe("setup-b");
  });

  it("스탯·엔딩 오류가 없으면 고르지 않는다", () => {
    const errors: FieldErrors<StoryFixture> = { startingSetups: [undefined, { name: fieldError() }] };
    expect(pick(errors, "startingSetups.1.name")).toBeUndefined();
  });
});
