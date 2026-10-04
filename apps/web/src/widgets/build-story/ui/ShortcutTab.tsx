import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useRef } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";

import {
  CollapsibleItemCard,
  focusNeighborToggle,
  ItemRemoveButton,
  itemOpenKey,
  useBuilderUiState,
} from "@/features/build-common";
import { FieldLabelText, type StoryBuilderFormValues, type StoryCollapsibleList } from "@/features/build-story";
import { firstLine } from "@/shared/lib/text/firstLine";

import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";

const SHORTCUT_LIST: StoryCollapsibleList = "shortcut";

/** 탭 전체가 선택사항(0개도 발행 가능), 작품 전역에 적용되는
 * 단축어 목록을 조회/수정/삭제 가능. */
export function ShortcutTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const { control, getValues } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "shortcuts" });
  const uiState = useBuilderUiState();
  const addButtonRef = useRef<HTMLButtonElement>(null);

  function handleAppend() {
    const id = crypto.randomUUID();
    // 새 항목을 열림으로 기록하는 일은 append 와 같은 핸들러에서 그보다 먼저 한다. 같은 커밋에 본문이 보여야 append 가
    // 주는 포커스가 숨은 입력칸에 걸려 헛돌지 않는다.
    uiState.open([itemOpenKey(SHORTCUT_LIST, id)]);
    append({ id, name: "", description: "", prompt: "" }, { focusName: `shortcuts.${fields.length}.name` });
  }

  function handleRemove(index: number) {
    // 지우기 전에 포커스를 옮긴다 — 지운 뒤로 미루면 누른 삭제 버튼이 사라지며 포커스가 문서 맨 앞으로 떨어진다.
    const keys = getValues("shortcuts").map((shortcut) => itemOpenKey(SHORTCUT_LIST, shortcut.id));
    focusNeighborToggle(keys, index, addButtonRef.current);
    remove(index);
  }

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1">
        <Label><FieldLabelText field="shortcuts" /></Label>
        <p className="text-sm text-muted-foreground">
          사용자가 채팅 중 짧은 명령어로 특정 동작을 실행할 수 있게 해요. 등록하지 않아도 발행할 수 있어요.
        </p>
      </div>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 단축어가 없어요.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {fields.map((field, index) => (
            <ShortcutRow key={field.id} id={field.id} index={index} onRemove={() => handleRemove(index)} />
          ))}
        </div>
      )}

      <Button ref={addButtonRef} type="button" variant="secondary" className="w-fit" onClick={handleAppend}>
        단축어 추가
      </Button>
    </div>
  );
}

type ShortcutRowProps = {
  id: string;
  index: number;
  onRemove: () => void;
};

/** 이름/설명/실행될 프롬프트(전부 필수), 작품 전역 적용이라
 * 스코프 선택 UI가 없다(KeywordNoteTab과 달리 순서/재정렬도 의미가 없어 StatTab과 동일하게
 * add/remove만 지원). 접힌 머리 줄은 이름과 설명 첫 줄로 단축어를 가른다. 열림 키는 폼 값의 id 다 — 필드 배열이 주는
 * id 는 탭을 다시 열 때마다 새로 발급돼 열림을 잃는다. */
function ShortcutRow({
  id,
  index,
  onRemove,
}: ShortcutRowProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    control,
    formState: { errors },
  } = form;
  const [shortcutId, name, description] = useWatch({
    control,
    name: [`shortcuts.${index}.id`, `shortcuts.${index}.name`, `shortcuts.${index}.description`],
  });
  const shortcutErrors = errors.shortcuts?.[index];
  const trimmedName = name.trim();

  return (
    <CollapsibleItemCard
      openKey={itemOpenKey(SHORTCUT_LIST, shortcutId)}
      title={name}
      placeholderTitle="새 단축어"
      srTitlePrefix={`${index + 1}번째 단축어: `}
      summary={firstLine(description)}
      hasError={!!shortcutErrors}
      trailing={
        <ItemRemoveButton
          label={trimmedName ? `${trimmedName} 단축어 삭제` : `${index + 1}번째 단축어 삭제`}
          onClick={onRemove}
        />
      }
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`shortcut-${id}-name`}><FieldLabelText field="shortcuts.*.name" /></Label>
        <Input
          id={`shortcut-${id}-name`}
          placeholder="단축어 이름을 입력해주세요"
          aria-invalid={!!shortcutErrors?.name}
          aria-describedby={shortcutErrors?.name ? `shortcut-${id}-name-error` : undefined}
          {...register(`shortcuts.${index}.name`)}
        />
        {shortcutErrors?.name && (
          <p id={`shortcut-${id}-name-error`} role="alert" className="text-xs text-destructive-text">
            {shortcutErrors.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`shortcut-${id}-description`}><FieldLabelText field="shortcuts.*.description" /></Label>
        <Textarea
          id={`shortcut-${id}-description`}
          placeholder="이 단축어가 어떤 동작을 하는지 설명해주세요"
          rows={2}
          aria-invalid={!!shortcutErrors?.description}
          aria-describedby={shortcutErrors?.description ? `shortcut-${id}-description-error` : undefined}
          {...register(`shortcuts.${index}.description`)}
        />
        <MediaTagOutsideNotice name={`shortcuts.${index}.description`} />
        {shortcutErrors?.description && (
          <p id={`shortcut-${id}-description-error`} role="alert" className="text-xs text-destructive-text">
            {shortcutErrors.description.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`shortcut-${id}-prompt`}><FieldLabelText field="shortcuts.*.prompt" /></Label>
        <Textarea
          id={`shortcut-${id}-prompt`}
          placeholder="단축어 실행 시 AI에게 전달할 프롬프트를 입력해주세요"
          rows={3}
          aria-invalid={!!shortcutErrors?.prompt}
          aria-describedby={shortcutErrors?.prompt ? `shortcut-${id}-prompt-error` : undefined}
          {...register(`shortcuts.${index}.prompt`)}
        />
        <MediaTagOutsideNotice name={`shortcuts.${index}.prompt`} />
        {shortcutErrors?.prompt && (
          <p id={`shortcut-${id}-prompt-error`} role="alert" className="text-xs text-destructive-text">
            {shortcutErrors.prompt.message}
          </p>
        )}
      </div>
    </CollapsibleItemCard>
  );
}
