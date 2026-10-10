import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { useRef, useState } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";

import {
  MAX_EXAMPLE_DIALOGUE_LINE_LENGTH,
  MAX_EXAMPLE_DIALOGUES,
  MAX_INTRO_LENGTH,
  MAX_PLAY_GUIDE_LENGTH,
} from "@/entities/content";
import type { CharacterBuilderFormValues, CharacterCollapsibleList } from "@/features/build-character";
import {
  FieldCharacterCount,
  CollapsibleItemCard,
  focusNeighborToggle,
  ItemRemoveButton,
  itemOpenKey,
  restoreUnderLimit,
  useBuilderUiState,
  useLimitedTextField,
  useUndoableRemoval,
} from "@/features/build-common";
import { firstLine } from "@/shared/lib/text/firstLine";
import { BuilderTextarea } from "@/shared/ui/BuilderTextarea";
import { RequiredText } from "@/shared/ui/RequiredText";

import { CharacterMacroNotice } from "./CharacterMacroNotice";

const EXAMPLE_DIALOGUE_LIST: CharacterCollapsibleList = "exampleDialogue";

/** 인트로는 단일 필드, 예시 대화는 고급 설정 뒤에 숨겨진 add/remove 전용
 * 목록(순서가 판정에 영향 없어 dnd-kit 불필요), 플레이가이드는 선택 입력. */
export function IntroTab() {
  const form = useFormContext<CharacterBuilderFormValues>();

  const {
    control,
    getValues,
    formState: { errors },
  } = form;
  const { fields, append, remove, insert } = useFieldArray({ control, name: "intro.exampleDialogues" });
  const uiState = useBuilderUiState();
  const addButtonRef = useRef<HTMLButtonElement>(null);
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(() => fields.length > 0);
  const firstMessage = useLimitedTextField<CharacterBuilderFormValues>("intro.firstMessage", MAX_INTRO_LENGTH);
  const playGuide = useLimitedTextField<CharacterBuilderFormValues>("intro.playGuide", MAX_PLAY_GUIDE_LENGTH);
  const isExampleDialogueFull = fields.length >= MAX_EXAMPLE_DIALOGUES;
  const removeWithUndo = useUndoableRemoval({
    getItems: () => getValues("intro.exampleDialogues"),
    remove,
    insert: (index, dialogue) => insert(index, dialogue, { shouldFocus: false }),
    openKey: (id) => itemOpenKey(EXAMPLE_DIALOGUE_LIST, id),
    objectPhrase: exampleDialogueObjectPhrase,
    // 스위치를 끈 채 되돌리면 무엇이 돌아왔는지 보이지 않고 포커스할 머리 줄도 없다 — 켜서 보인다.
    beforeRestore: () => setIsAdvancedOpen(true),
    // 그 사이 추가해 상한이 찼으면 되살리지 않는다 — 넘은 목록은 서버가 초안 저장을 통째로 거절한다.
    decideRestore: (items, dialogue) =>
      restoreUnderLimit(items.length, dialogue, MAX_EXAMPLE_DIALOGUES, `예시 대화는 최대 ${MAX_EXAMPLE_DIALOGUES}개까지예요.`),
  });

  // 스위치를 끈 채 이 탭에서 발행하면 예시 대화 오류가 화면에 없는 입력칸에 걸려 아무것도 보이지 않는다. 그래서 발행이 예시
  // 대화에 새 오류 묶음을 내면 그때 한 번 스위치를 켠다. 오류가 남은 채 사용자가 다시 끄는 것은 막지 않는다 — 오류 객체가
  // 새로 바뀔 때만 켠다. 다른 탭에서 발행해 이 탭으로 넘어올 때는 탭이 다시 마운트되며 항목이 있으면 켜진 채 시작한다.
  const exampleDialogueErrors = errors.intro?.exampleDialogues;
  // 목록 자체에 걸린 오류(개수 상한). 배열 자리 오류는 `.message` 와 `.root.message` 로 갈릴 수 있어 둘 다 읽는다.
  const exampleDialogueListError = exampleDialogueErrors?.message ?? exampleDialogueErrors?.root?.message;
  const [seenExampleDialogueErrors, setSeenExampleDialogueErrors] = useState(exampleDialogueErrors);
  if (exampleDialogueErrors !== seenExampleDialogueErrors) {
    setSeenExampleDialogueErrors(exampleDialogueErrors);
    if (exampleDialogueErrors) setIsAdvancedOpen(true);
  }

  function handleAppend() {
    // 상한에서도 버튼은 `aria-disabled` 로 남는다(아래 버튼 주석). 실제 차단은 여기다.
    if (isExampleDialogueFull) return;
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
    removeWithUndo(index);
  }

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-intro-first-message"><RequiredText>인트로 (첫 대화 본문)</RequiredText></Label>
        <BuilderTextarea
          id="character-intro-first-message"
          placeholder="사용자와의 첫 대화에서 캐릭터가 건넬 말을 입력해주세요"
          rows={5}
          aria-invalid={!!errors.intro?.firstMessage}
          aria-describedby={errors.intro?.firstMessage ? "character-intro-first-message-count character-intro-first-message-error" : "character-intro-first-message-count"}
          {...firstMessage.registration}
        />
        <FieldCharacterCount
          id="character-intro-first-message-count"
          name={firstMessage.registration.name}
          max={MAX_INTRO_LENGTH}
          isTruncated={firstMessage.isTruncated}
        />
        <CharacterMacroNotice name="intro.firstMessage" />
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
          {/* 상한에서도 버튼을 트리에 남기고 `aria-disabled` 로만 잠근다 — `disabled` 는 누르는 순간 포커스를 body 로
              떨어뜨리고, 지우면 왜 더 못 넣는지가 사라진다. */}
          <Button
            ref={addButtonRef}
            type="button"
            variant="secondary"
            aria-disabled={isExampleDialogueFull}
            aria-describedby={isExampleDialogueFull ? "character-intro-dialogue-limit" : undefined}
            className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
            onClick={handleAppend}
          >
            예시 대화 추가
          </Button>
          {isExampleDialogueFull && (
            <p id="character-intro-dialogue-limit" className="text-xs break-keep text-muted-foreground">
              예시 대화는 최대 {MAX_EXAMPLE_DIALOGUES}개예요. 더 넣으려면 하나를 지워 주세요.
            </p>
          )}
          {!!exampleDialogueListError && (
            <p role="alert" className="text-xs break-keep text-destructive-text">
              {exampleDialogueListError}
            </p>
          )}
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-intro-play-guide">플레이가이드</Label>
        <BuilderTextarea
          id="character-intro-play-guide"
          placeholder="사용자에게 노출할 플레이 안내를 입력해주세요"
          rows={3}
          aria-describedby="character-intro-play-guide-count"
          {...playGuide.registration}
        />
        <FieldCharacterCount
          id="character-intro-play-guide-count"
          name={playGuide.registration.name}
          max={MAX_PLAY_GUIDE_LENGTH}
          isTruncated={playGuide.isTruncated}
        />
        <CharacterMacroNotice name="intro.playGuide" />
      </div>
    </div>
  );
}

/** 토스트에 담을 사용자 대사 앞부분의 길이(코드 포인트). 긴 대사가 토스트 문장을 늘이지 않게 자른다. */
const DIALOGUE_SNIPPET_LENGTH = 20;

/** 토스트 문장의 목적어("‘안녕, 오랜만이야’ 예시 대화를") — 이름이 없어 사용자 대사 첫 줄 앞부분으로 가른다. */
function exampleDialogueObjectPhrase(dialogue: { userLine: string }): string {
  const characters = [...firstLine(dialogue.userLine)];
  if (characters.length === 0) return "빈 예시 대화를";
  const snippet =
    characters.length > DIALOGUE_SNIPPET_LENGTH
      ? `${characters.slice(0, DIALOGUE_SNIPPET_LENGTH).join("")}…`
      : characters.join("");
  return `‘${snippet}’ 예시 대화를`;
}

type ExampleDialogueItemProps = {
  index: number;
  onRemove: () => void;
};

/** 예시 대화 한 쌍. 이름 칸이 없어 머리 줄 제목은 번호이고, 접혀 있어도 어느 대화인지 가를 수 있게 사용자 대사 첫 줄을
 * 요약으로 보인다. 열림 키는 폼 값의 id 다 — 필드 배열이 주는 id 는 탭을 다시 열 때마다 새로 발급돼 열림을 잃는다. */
function ExampleDialogueItem({ index, onRemove }: ExampleDialogueItemProps) {
  const {
    control,
    formState: { errors },
  } = useFormContext<CharacterBuilderFormValues>();
  const userLine = useLimitedTextField<CharacterBuilderFormValues>(
    `intro.exampleDialogues.${index}.userLine`,
    MAX_EXAMPLE_DIALOGUE_LINE_LENGTH,
  );
  const characterLine = useLimitedTextField<CharacterBuilderFormValues>(
    `intro.exampleDialogues.${index}.characterLine`,
    MAX_EXAMPLE_DIALOGUE_LINE_LENGTH,
  );
  const dialogue = useWatch({ control, name: `intro.exampleDialogues.${index}` });
  const itemErrors = errors.intro?.exampleDialogues?.[index];
  const userLineError = itemErrors?.userLine;
  const userLineErrorId = `character-intro-dialogue-${dialogue.id}-user-line-error`;
  const characterLineError = itemErrors?.characterLine;
  const characterLineErrorId = `character-intro-dialogue-${dialogue.id}-character-line-error`;
  const userLineCountId = `character-intro-dialogue-${dialogue.id}-user-line-count`;
  const characterLineCountId = `character-intro-dialogue-${dialogue.id}-character-line-count`;
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
        <BuilderTextarea
          placeholder="사용자 대사"
          rows={2}
          aria-invalid={!!userLineError}
          aria-describedby={userLineError ? `${userLineCountId} ${userLineErrorId}` : userLineCountId}
          {...userLine.registration}
        />
        <FieldCharacterCount
          id={userLineCountId}
          name={userLine.registration.name}
          max={MAX_EXAMPLE_DIALOGUE_LINE_LENGTH}
          isTruncated={userLine.isTruncated}
        />
        <CharacterMacroNotice name={`intro.exampleDialogues.${index}.userLine`} />
        {userLineError && (
          <p id={userLineErrorId} role="alert" className="text-xs text-destructive-text">
            {userLineError.message}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <BuilderTextarea
          placeholder="캐릭터 대사"
          rows={4}
          aria-invalid={!!characterLineError}
          aria-describedby={characterLineError ? `${characterLineCountId} ${characterLineErrorId}` : characterLineCountId}
          {...characterLine.registration}
        />
        <FieldCharacterCount
          id={characterLineCountId}
          name={characterLine.registration.name}
          max={MAX_EXAMPLE_DIALOGUE_LINE_LENGTH}
          isTruncated={characterLine.isTruncated}
        />
        <CharacterMacroNotice name={`intro.exampleDialogues.${index}.characterLine`} />
        {characterLineError && (
          <p id={characterLineErrorId} role="alert" className="text-xs text-destructive-text">
            {characterLineError.message}
          </p>
        )}
      </div>
    </CollapsibleItemCard>
  );
}
