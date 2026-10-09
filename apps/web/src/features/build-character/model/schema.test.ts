import { describe, expect, it } from "vitest";

import { createEmptyDraft } from "@/entities/content";

import { characterBuilderSchema } from "./schema";
import { serverToForm } from "./serverToForm";

function validFullForm() {
  return {
    profile: {
      name: "루나",
      oneLiner: "밤에만 문을 여는 사서",
      image: { assetId: "asset-thumbnail-1" },
    },
    intro: { firstMessage: "또 늦은 시간에 오셨네요." },
    prompt: { characterPrompt: "느리고 조용한 말투를 쓴다. 책 이야기를 좋아한다." },
    registration: {
      description: "밤의 도서관에서 만나는 사서",
      genre: "genre-romance",
      target: "all" as const,
    },
  };
}

/** 초안을 담으려고 nullable로 둔 3필드는 화면에 `*`가
 * 붙어 있고 서버도 요구한다. 타입은 그대로 두고 refine이 상시 검증해 서버 400 왕복 전에 걸린다
 * (스토리 빌더의 같은 3필드와 짝, `features/build-story/model/schema.test.ts`). */
describe("characterBuilderSchema publish-required nullable fields", () => {
  it("rejects a null profile.image", () => {
    const result = characterBuilderSchema.safeParse({
      ...validFullForm(),
      profile: { ...validFullForm().profile, image: null },
    });

    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "profile",
      "image",
    ]);
  });

  it("rejects a null registration.genre", () => {
    const result = characterBuilderSchema.safeParse({
      ...validFullForm(),
      registration: { ...validFullForm().registration, genre: null },
    });

    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "registration",
      "genre",
    ]);
  });

  it("rejects a null registration.target", () => {
    const result = characterBuilderSchema.safeParse({
      ...validFullForm(),
      registration: { ...validFullForm().registration, target: null },
    });

    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "registration",
      "target",
    ]);
  });

  it("passes once all three are filled", () => {
    expect(characterBuilderSchema.safeParse(validFullForm()).success).toBe(true);
  });
});

// 발행 실패 때 같은 탭 안의 첫 오류는 검증 오류의 순서를 따른다. 화면 맨 위 칸인 대표 이미지가 첫 오류여야 포커스가 둘째 칸(이름)으로
// 먼저 가지 않는다.
describe("characterBuilderSchema issue order", () => {
  it("puts profile.image first for an empty draft", () => {
    const draft = createEmptyDraft("character");
    if (draft.type !== "character") throw new Error("캐릭터 빈 초안이 아니에요.");
    const issues = characterBuilderSchema.safeParse(serverToForm(draft)).error?.issues ?? [];
    expect(issues.map((issue) => issue.path.join(".")).slice(0, 3)).toEqual([
      "profile.image",
      "profile.name",
      "profile.oneLiner",
    ]);
  });
});
