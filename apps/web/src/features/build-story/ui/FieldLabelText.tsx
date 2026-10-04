import { RequiredText } from "@/shared/ui/RequiredText";

import {
  STORY_FIELD_LABELS,
  type ConditionalStoryFieldKey,
  type StoryFieldKey,
} from "../model/fieldLabels";

type FieldLabelTextProps =
  | { field: Exclude<StoryFieldKey, ConditionalStoryFieldKey>; isRequired?: never }
  | { field: ConditionalStoryFieldKey; isRequired: boolean };

/**
 * 스토리 빌더 칸 라벨의 글자. 라벨 글자와 필수 별표를 칸 라벨 상수 하나에서 그려, 빌더와 작성 가이드가 같은 칸을 같은
 * 이름·같은 별표로 보이게 한다. 필수가 조건부인 칸만 `isRequired` 를 받는다.
 *
 * 괄호 글까지 한 `<span>` 으로 묶는 이유: `<Label>` 은 `flex gap-2` 라 조각을 따로 두면 사이가 띄어쓰기 한 칸이 아니라
 * 8px 로 벌어진다.
 */
export function FieldLabelText({ field, isRequired }: FieldLabelTextProps) {
  const fieldLabel: { label: string; required: boolean | "conditional"; note?: string } = STORY_FIELD_LABELS[field];
  const isShownRequired = fieldLabel.required === "conditional" ? isRequired === true : fieldLabel.required;

  return (
    <span>
      {isShownRequired ? <RequiredText>{fieldLabel.label}</RequiredText> : fieldLabel.label}
      {fieldLabel.note ? ` (${fieldLabel.note})` : null}
    </span>
  );
}
