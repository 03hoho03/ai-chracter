import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useId } from "react";
import { useFormContext } from "react-hook-form";

import {
  FieldCharacterCount,
  CollapsibleItemCard,
  ItemRemoveButton,
  itemOpenKey,
  useLimitedTextField,
} from "@/features/build-common";
import {
  countRules,
  FieldLabelText,
  hasRuleWithMissingStat,
  MAX_SITUATION_NOTE_CONTENT_LENGTH,
  MAX_SITUATION_NOTE_NAME_LENGTH,
  MAX_SITUATION_NOTE_RULES,
  SITUATION_NOTE_RULE_LIMIT_MESSAGE,
  situationNoteConditionSummary,
  situationNoteTitle,
  type SituationNoteValues,
  type StatDefValues,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";

import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";
import { RuleListEditor } from "./RuleListEditor";
import { StoryMacroNotice } from "./StoryMacroNotice";

const SITUATION_NOTE_LIST: StoryCollapsibleList = "situationNote";
const RULE_GROUP_LIST: StoryCollapsibleList = "situationNoteRuleGroup";

/** 조건은 필수다 — 조건이 없는 노트는 발행할 수 없고 대화에도 실리지 않는다. 그룹 안에도 같은 문장이 쓰인다. */
const CONDITIONS_EMPTY_TEXT = "조건을 하나 이상 넣어 주세요. 조건 없이 늘 실을 내용은 스토리 설정에 적어요.";
const NO_STATS_REASON = "이 시작설정에 스탯이 없어 조건을 만들 수 없어요.";

type SituationNoteCardProps = {
  startingSetupIndex: number;
  noteIndex: number;
  /** 지금 노트 값 — 목록이 이미 구독하고 있어 카드가 같은 값을 따로 구독하지 않는다. */
  note: SituationNoteValues;
  stats: StatDefValues[];
  onRemove: () => void;
};

/**
 * 상황 노트 한 장. 머리 줄은 제목(이름, 비면 상황 글의 첫 줄)·조건 요약·삭제이고, 본문은 이름 → 조건 → 상황 순서다 — "이
 * 조건이면 → 이 사실"로 읽히게 조건을 상황 앞에 둔다.
 *
 * 이름·상황 칸은 등록한 입력이라 입력할 때 상한(서버와 같은 코드 포인트)에서 잘라 상한을 넘는 글이 폼에 생기지 않는다.
 * 조건은 제어 컴포넌트라 바뀐 목록을 통째로 써 넣는다. 발행을 한 번
 * 시도한 뒤에는 조건을 바꿀 때 다시 검증해, 조건을 채우는 즉시 "조건을 넣어 주세요" 오류가 풀린다(입력 칸은 RHF 가 같은
 * 일을 한다).
 */
export function SituationNoteCard({ startingSetupIndex, noteIndex, note, stats, onRemove }: SituationNoteCardProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    setValue,
    formState: { errors, isSubmitted },
  } = form;
  const notePath = `startingSetups.${startingSetupIndex}.situationNotes.${noteIndex}` as const;
  const nameField = useLimitedTextField<StoryBuilderFormValues>(`${notePath}.name`, MAX_SITUATION_NOTE_NAME_LENGTH);
  const contentField = useLimitedTextField<StoryBuilderFormValues>(`${notePath}.content`, MAX_SITUATION_NOTE_CONTENT_LENGTH);
  const noteErrors = errors.startingSetups?.[startingSetupIndex]?.situationNotes?.[noteIndex];
  // 조건 목록 자체에 걸린 오류(조건 없음·상한). 배열 자리 오류는 `.message` 와 `.root.message` 로 갈릴 수 있어 둘 다 읽는다.
  const conditionsError = noteErrors?.conditionRules?.message ?? noteErrors?.conditionRules?.root?.message;
  const position = noteIndex + 1;
  const trimmedName = note.name.trim();
  const generatedId = useId();
  const ids = {
    name: `${generatedId}-name`,
    nameCount: `${generatedId}-name-count`,
    nameError: `${generatedId}-name-error`,
    conditionsLabel: `${generatedId}-conditions`,
    conditionsCount: `${generatedId}-conditions-count`,
    conditionsError: `${generatedId}-conditions-error`,
    content: `${generatedId}-content`,
    contentCount: `${generatedId}-content-count`,
    contentError: `${generatedId}-content-error`,
  };

  return (
    <CollapsibleItemCard
      openKey={itemOpenKey(SITUATION_NOTE_LIST, note.id)}
      title={situationNoteTitle(note)}
      placeholderTitle="새 상황 노트"
      srTitlePrefix={`${position}번째 상황 노트: `}
      summary={situationNoteConditionSummary(note.conditionRules, stats)}
      // 지워진 스탯을 쓰는 조건은 폼 오류가 아니라 데이터 사실이라 따로 본다 — 접혀 있어도 머리 줄에 경고가 보여야 찾는다.
      hasError={!!noteErrors || hasRuleWithMissingStat(note.conditionRules, stats)}
      trailing={
        <ItemRemoveButton
          // 상황 글은 길 수 있어 삭제 버튼 이름에는 이름만 쓴다.
          label={trimmedName ? `${trimmedName} 상황 노트 삭제` : `${position}번째 상황 노트 삭제`}
          onClick={onRemove}
        />
      }
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.name}><FieldLabelText field="startingSetups.*.situationNotes.*.name" /></Label>
        <Input
          id={ids.name}
          placeholder="목록에서 알아볼 이름(선택)"
          aria-invalid={!!noteErrors?.name}
          aria-describedby={noteErrors?.name ? `${ids.nameCount} ${ids.nameError}` : ids.nameCount}
          {...nameField.registration}
        />
        <FieldCharacterCount
          id={ids.nameCount}
          name={nameField.registration.name}
          max={MAX_SITUATION_NOTE_NAME_LENGTH}
          isTruncated={nameField.isTruncated}
        />
        {!!noteErrors?.name && (
          <p id={ids.nameError} role="alert" className="text-xs text-destructive-text">
            {noteErrors.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2" role="group" aria-labelledby={ids.conditionsLabel}>
        <div className="flex items-baseline justify-between gap-2">
          <span id={ids.conditionsLabel} className="text-sm leading-none font-medium">
            <FieldLabelText field="startingSetups.*.situationNotes.*.conditionRules" />
          </span>
          <span id={ids.conditionsCount} className="text-xs tabular-nums text-muted-foreground">
            조건 {countRules(note.conditionRules)} / {MAX_SITUATION_NOTE_RULES}
          </span>
        </div>
        <RuleListEditor
          items={note.conditionRules}
          stats={stats}
          allowGroups
          emptyText={CONDITIONS_EMPTY_TEXT}
          groupList={RULE_GROUP_LIST}
          fieldPath={`${notePath}.conditionRules`}
          ruleLimit={{ max: MAX_SITUATION_NOTE_RULES, reason: SITUATION_NOTE_RULE_LIMIT_MESSAGE }}
          noStatsReason={NO_STATS_REASON}
          onChange={(next) =>
            setValue(`${notePath}.conditionRules`, next, { shouldDirty: true, shouldValidate: isSubmitted })
          }
        />
        {!!conditionsError && (
          <p id={ids.conditionsError} role="alert" className="text-xs text-destructive-text">
            {conditionsError}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.content}>
          <FieldLabelText field="startingSetups.*.situationNotes.*.content" />
        </Label>
        <Textarea
          id={ids.content}
          placeholder="예: 오늘은 가을 상영회 당일이다. 동아리 사람들은 아침부터 강당에 모여 있다."
          rows={3}
          aria-invalid={!!noteErrors?.content}
          aria-describedby={noteErrors?.content ? `${ids.contentCount} ${ids.contentError}` : ids.contentCount}
          {...contentField.registration}
        />
        <FieldCharacterCount
          id={ids.contentCount}
          help="조건이 맞는 턴에 ‘지금 이야기 속 사실’로 전해져요. ‘~해라’ 같은 지시 대신 사실로 적어 주세요."
          name={contentField.registration.name}
          max={MAX_SITUATION_NOTE_CONTENT_LENGTH}
          isTruncated={contentField.isTruncated}
        />
        <MediaTagOutsideNotice name={`${notePath}.content`} />
        <StoryMacroNotice name={`${notePath}.content`} />
        {!!noteErrors?.content && (
          <p id={ids.contentError} role="alert" className="text-xs text-destructive-text">
            {noteErrors.content.message}
          </p>
        )}
      </div>
    </CollapsibleItemCard>
  );
}
