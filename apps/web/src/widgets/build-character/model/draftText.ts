import { CHARACTER_FIELD_LABELS, CHARACTER_TABS, type CharacterBuilderFormValues } from "@/features/build-character";
import { draftPlainText } from "@/features/build-common";

import { CHARACTER_TAB_STEPS } from "./steps";

/** 라벨 표에 있지만 값이 고르는 항목의 키(장르 id·타겟)라 글로 옮겨도 뜻이 없는 칸. */
const CHARACTER_CHOICE_FIELDS = new Set<string>([
  "registration.genre",
  "registration.target",
] satisfies (keyof typeof CHARACTER_FIELD_LABELS)[]);

/** 저장이 실패하거나 연결이 끊겼을 때 [내용 복사]가 클립보드에 넣는 캐릭터 초안 글. */
export function characterDraftText(values: CharacterBuilderFormValues): string {
  return draftPlainText(values, {
    tabs: CHARACTER_TABS,
    steps: CHARACTER_TAB_STEPS,
    labels: CHARACTER_FIELD_LABELS,
    choiceFields: CHARACTER_CHOICE_FIELDS,
  });
}
