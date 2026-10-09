import { createEmptyDraft } from "@/entities/content";
import { characterBuilderSchema, CHARACTER_TABS, serverToForm } from "@/features/build-character";
import { requiredTabIds } from "@/features/build-common";

function emptyCharacterForm() {
  const draft = createEmptyDraft("character");
  if (draft.type !== "character") throw new Error("캐릭터 빈 초안이 아니에요.");
  return serverToForm(draft);
}

/** 탭 줄이 필수 별표를 붙이는 탭. 빈 초안을 발행 검증에 넣어 오류가 나는 탭이다(`requiredTabIds`). 화면을 그릴 때마다
 * 다시 검사하지 않도록 모듈을 읽을 때 한 번만 계산한다. */
export const CHARACTER_REQUIRED_TAB_IDS = requiredTabIds(
  characterBuilderSchema.safeParse(emptyCharacterForm()).error?.issues.map((issue) => issue.path) ?? [],
  CHARACTER_TABS,
);
