import { createEmptyDraft } from "@/entities/content";
import { requiredTabIds } from "@/features/build-common";
import { serverToForm, storyBuilderSchema, STORY_TABS } from "@/features/build-story";

function emptyStoryForm() {
  const draft = createEmptyDraft("story");
  if (draft.type !== "story") throw new Error("스토리 빈 초안이 아니에요.");
  return serverToForm(draft);
}

/** 탭 줄이 필수 별표를 붙이는 탭. 빈 초안을 발행 검증에 넣어 오류가 나는 탭이다(`requiredTabIds`). 화면을 그릴 때마다
 * 다시 검사하지 않도록 모듈을 읽을 때 한 번만 계산한다. */
export const STORY_REQUIRED_TAB_IDS = requiredTabIds(
  storyBuilderSchema.safeParse(emptyStoryForm()).error?.issues.map((issue) => issue.path) ?? [],
  STORY_TABS,
);
