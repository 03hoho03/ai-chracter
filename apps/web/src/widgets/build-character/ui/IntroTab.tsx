import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useRef, useState } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";

import type { CharacterBuilderFormValues, CharacterCollapsibleList } from "@/features/build-character";
import {
  CollapsibleItemCard,
  firstLine,
  focusNeighborToggle,
  ItemRemoveButton,
  itemOpenKey,
  useBuilderUiState,
} from "@/features/build-common";
import { RequiredText } from "@/shared/ui/RequiredText";

const EXAMPLE_DIALOGUE_LIST: CharacterCollapsibleList = "exampleDialogue";

/** 인트로는 단일 필드, 예시 대화는 고급설정 뒤에 숨겨진 add/remove 전용
 * 목록(순서가 판정에 영향 없어 dnd-kit 불필요), 플레이가이드는 선택 입력. */
export function IntroTab() {
  const form = useFormContext<CharacterBuilderFormValues>();

  const {
    register,
    control,
    getValues,
    formState: { errors },
  } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "intro.exampleDialogues" });
  const uiState = useBuilderUiState();
  const addButtonRef = useRef<HTMLButtonElement>(null);
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(() => fields.length > 0);

  // 스위치를 끈 채 이 탭에서 발행하면 예시 대화 오류가 화면에 없는 입력칸에 걸려 아무것도 보이지 않는다. 그래서 발행이 예시
  // 대화에 새 오류 묶음을 내면 그때 한 번 스위치를 켠다. 오류가 남은 채 사용자가 다시 끄는 것은 막지 않는다 — 오류 객체가
  // 새로 바뀔 때만 켠다. 다른 탭에서 발행해 이 탭으로 넘어올 때는 탭이 다시 마운트되며 항목이 있으면 켜진 채 시작한다.
  const exampleDialogueErrors = errors.intro?.exampleDialogues;
  const [seenExampleDialogueErrors, setSeenExampleDialogueErrors] = useState(exampleDialogueErrors);
  if (exampleDialogueErrors !== seenExampleDialogueErrors) {
    setSeenExampleDialogueErrors(exampleDialogueErrors);
    if (exampleDialogueErrors) setIsAdvancedOpen(true);
  }

  function handleAppend() {
    const id = crypto.randomUUID();
    // 새 항목을 열림으로 기록하는 일은 append 와 같은 핸들러에서 그보다 먼저 한다. 같은 커밋에 본문이 보여야 append 가
    // 주는 포커스가 숨은 입력칸에 걸려 헛돌지 않는다.
    uiState.open([itemOpenKey(EXAMPLE_DIALOGUE_LIST, id)]);
    append({ id, userLine: "", characterLine: "" }, { focusName: `intro.exampleDialogues.${fields.length}.userLine` });
  }

  function handleRemove(index: number) {
    // 지우기 전에 포커스를 옮긴다 — 지운 뒤로 미루면 누른 삭제 버튼이 사라지며 포커스가 문서 맨 앞으로 떨어진다.
    const keys = getValues("intro.exampleDialogues").map((dialogue) => itemOpenKey(EXAMPLE_DIALOGUE_LIST, dialogue.id));
    focusNeighborToggle(keys, index, addButtonRef.current);
    remove(index);
  }

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-intro-first-message"><RequiredText>인트로 (첫 대화 본문)</RequiredText></Label>
        <Textarea
          id="character-intro-first-message"
          placeholder="사용자와의 첫 대화에서 캐릭터가 건넬 말을 입력해주세요"
          rows={4}
          aria-invalid={!!errors.intro?.firstMessage}
          aria-describedby={errors.intro?.firstMessage ? "character-intro-first-message-error" : undefined}
          {...register("intro.firstMessage")}
        />
        {errors.intro?.firstMessage && (
          <p id="character-intro-first-message-error" role="alert" className="text-xs text-destructive-text">
            {errors.intro.firstMessage.message}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor="character-intro-advanced-toggle">고급 설정</Label>
          <p className="text-sm text-muted-foreground">예시 대화로 캐릭터의 말투를 보여줄 수 있어요</p>
        </div>
        <Switch
          id="character-intro-advanced-toggle"
          checked={isAdvancedOpen}
          onCheckedChange={setIsAdvancedOpen}
        />
      </div>

      {isAdvancedOpen && (
        <div className="flex flex-col gap-4">
          <Label>예시 대화</Label>
          {fields.map((field, index) => (
            <ExampleDialogueItem key={field.id} index={index} onRemove={() => handleRemove(index)} />
          ))}
          <Button ref={addButtonRef} type="button" variant="secondary" onClick={handleAppend}>
            예시 대화 추가
          </Button>
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-intro-play-guide">플레이가이드</Label>
        <Textarea
          id="character-intro-play-guide"
          placeholder="사용자에게 노출할 플레이 안내를 입력해주세요"
          rows={3}
          {...register("intro.playGuide")}
        />
      </div>
    </div>
  );
}

type ExampleDialogueItemProps = {
  index: number;
  onRemove: () => void;
};

/** 예시 대화 한 쌍. 이름 칸이 없어 머리 줄 제목은 번호이고, 접혀 있어도 어느 대화인지 가를 수 있게 사용자 대사 첫 줄을
 * 요약으로 보인다. 열림 키는 폼 값의 id 다 — 필드 배열이 주는 id 는 탭을 다시 열 때마다 새로 발급돼 열림을 잃는다. */
function ExampleDialogueItem({ index, onRemove }: ExampleDialogueItemProps) {
  const {
    register,
    control,
    formState: { errors },
  } = useFormContext<CharacterBuilderFormValues>();
  const dialogue = useWatch({ control, name: `intro.exampleDialogues.${index}` });
  const itemErrors = errors.intro?.exampleDialogues?.[index];
  const userLineError = itemErrors?.userLine;
  const userLineErrorId = `character-intro-dialogue-${dialogue.id}-user-line-error`;
  const characterLineError = itemErrors?.characterLine;
  const characterLineErrorId = `character-intro-dialogue-${dialogue.id}-character-line-error`;
  const title = `예시 대화 ${index + 1}`;

  return (
    <CollapsibleItemCard
      openKey={itemOpenKey(EXAMPLE_DIALOGUE_LIST, dialogue.id)}
      title=""
      placeholderTitle={title}
      summary={firstLine(dialogue.userLine)}
      hasError={!!itemErrors}
      trailing={<ItemRemoveButton label={`${title} 삭제`} onClick={onRemove} />}
    >
      <div className="flex flex-col gap-1">
        <Textarea
          placeholder="사용자 대사"
          rows={2}
          aria-invalid={!!userLineError}
          aria-describedby={userLineError ? userLineErrorId : undefined}
          {...register(`intro.exampleDialogues.${index}.userLine`)}
        />
        {userLineError && (
          <p id={userLineErrorId} role="alert" className="text-xs text-destructive-text">
            {userLineError.message}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <Textarea
          placeholder="캐릭터 대사"
          rows={4}
          aria-invalid={!!characterLineError}
          aria-describedby={characterLineError ? characterLineErrorId : undefined}
          {...register(`intro.exampleDialogues.${index}.characterLine`)}
        />
        {characterLineError && (
          <p id={characterLineErrorId} role="alert" className="text-xs text-destructive-text">
            {characterLineError.message}
          </p>
        )}
      </div>
    </CollapsibleItemCard>
  );
}
