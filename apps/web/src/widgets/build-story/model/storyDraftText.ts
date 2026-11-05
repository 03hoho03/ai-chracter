import { draftPlainText } from "@/features/build-common";
import { STORY_FIELD_LABELS, STORY_TABS, type StoryBuilderFormValues } from "@/features/build-story";

import { STORY_TAB_STEPS } from "./steps";

/** 라벨 표에 있지만 값이 고르는 항목의 키(템플릿·아이콘·색·스탯 id·장르 id·타겟·공개범위·허락 범위)라 글로 옮겨도 뜻이 없는 칸. */
const STORY_CHOICE_FIELDS = new Set<string>([
  "storySetting.promptTemplate",
  "startingSetups.*.stats.*.icon",
  "startingSetups.*.stats.*.color",
  "startingSetups.*.endings.*.priorityStatId",
  "registration.genre",
  "registration.target",
  "registration.visibility",
  "registration.novelPermission",
] satisfies (keyof typeof STORY_FIELD_LABELS)[]);

/** 저장이 실패하거나 연결이 끊겼을 때 [내용 복사]가 클립보드에 넣는 스토리 초안 글. */
export function storyDraftText(values: StoryBuilderFormValues): string {
  return draftPlainText(values, {
    tabs: STORY_TABS,
    steps: STORY_TAB_STEPS,
    labels: STORY_FIELD_LABELS,
    choiceFields: STORY_CHOICE_FIELDS,
  });
}
