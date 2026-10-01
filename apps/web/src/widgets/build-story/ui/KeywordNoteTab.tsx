import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Trash2, X } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";

import {
  MAX_KEYWORD_NOTE_CONTENT_LENGTH,
  MAX_KEYWORD_NOTES,
  triggerKeywordError,
  type StartingSetupValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";

import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";

/** 탭 전체가 선택사항(0개도 발행 가능). */
export function KeywordNoteTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    control,
    formState: { errors },
  } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "keywordNotes" });
  const startingSetups = useWatch({ control, name: "startingSetups" });
  // 배열 자체의 위반(노트 수 상한)이 담기는 자리는 탭 마운트 상태에 따라 `.message` 와 `.root.message` 로 갈린다
  // (StartingSetupTab 의 같은 자리 주석 참고). 둘 다 읽는다.
  const notesError = errors.keywordNotes?.message ?? errors.keywordNotes?.root?.message;

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1">
        <Label>키워드북</Label>
        <p className="text-sm text-muted-foreground">
          특정 단어가 언급되면 자동으로 참고할 설정 정보를 등록해요. 등록하지 않아도 발행할 수 있어요.
        </p>
        {!!notesError && (
          <p role="alert" className="text-xs text-destructive-text">
            {notesError}
          </p>
        )}
      </div>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 키워드 노트가 없어요.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {fields.map((field, index) => (
            <KeywordNoteRow
              key={field.id}
              id={field.id}
              index={index}
              startingSetups={startingSetups}
              onRemove={() => remove(index)}
            />
          ))}
        </div>
      )}

      {/* 상한에 닿으면 추가 버튼 대신 이유를 보여 준다(StartingSetupTab 의 설정 추가와 같은 형태 — 추가하면
          append 가 새 노트로 포커스를 옮기므로 버튼이 사라져도 포커스를 잃지 않는다). 51번째 노트는 서버가 저장을
          거절해 그 초안의 자동저장 전체가 멈추므로 폼에 들어가지 않게 한다. */}
      {fields.length < MAX_KEYWORD_NOTES ? (
        <Button
          type="button"
          variant="secondary"
          className="w-fit"
          onClick={() =>
            append({
              id: crypto.randomUUID(),
              content: "",
              triggerKeywords: [],
              scope: { kind: "global" },
            })
          }
        >
          노트 추가
        </Button>
      ) : (
        <p className="text-sm text-muted-foreground">노트는 최대 {MAX_KEYWORD_NOTES}개까지 만들 수 있어요.</p>
      )}
    </div>
  );
}

type KeywordNoteRowProps = {
  id: string;
  index: number;
  startingSetups: StartingSetupValues[];
  onRemove: () => void;
};

/** 정보(필수)/트리거 키워드(필수, 태그 입력)/적용 대상(필수,
 * 스토리 전체 또는 특정 시작설정). 트리거 키워드 칩은 StartingSetupTab의 추천 답변 칩 패턴을,
 * 시작설정 선택은 StatTab의 ToggleGroup 패턴을 재사용한다. */
function KeywordNoteRow({
  id,
  index,
  startingSetups,
  onRemove,
}: KeywordNoteRowProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    control,
    setValue,
    getValues,
    formState: { errors },
  } = form;
  const content = useWatch({ control, name: `keywordNotes.${index}.content` });
  const triggerKeywords = useWatch({ control, name: `keywordNotes.${index}.triggerKeywords` });
  const scope = useWatch({ control, name: `keywordNotes.${index}.scope` });
  const [keywordInput, setKeywordInput] = useState("");
  const [keywordRefusal, setKeywordRefusal] = useState<string>();
  const noteErrors = errors.keywordNotes?.[index];

  function addKeyword() {
    const trimmed = keywordInput.trim();
    if (!trimmed) {
      setKeywordInput("");
      return;
    }
    // 서버가 거절할 키워드(길이·개수·대소문자만 다른 중복)는 폼에 넣지 않는다 — 자동저장은 발행 검사를 거치지 않아
    // 한 번 들어가면 그 초안 저장 전체가 멈춘다. 거절할 때는 쓴 글을 지우지 않고 이유를 보여 준다.
    const refusal = triggerKeywordError(trimmed, triggerKeywords);
    if (refusal) {
      setKeywordRefusal(refusal);
      return;
    }
    setKeywordInput("");
    setValue(`keywordNotes.${index}.triggerKeywords`, [...triggerKeywords, trimmed], { shouldDirty: true });
  }

  function removeKeyword(keyword: string) {
    setKeywordRefusal(undefined);
    setValue(
      `keywordNotes.${index}.triggerKeywords`,
      triggerKeywords.filter((item) => item !== keyword),
      { shouldDirty: true },
    );
  }

  function handleScopeKindChange(value: string) {
    if (!value) return;
    if (value === "global") {
      setValue(`keywordNotes.${index}.scope`, { kind: "global" }, { shouldDirty: true });
      return;
    }
    const currentScope = getValues(`keywordNotes.${index}.scope`);
    const defaultSetupId = currentScope.kind === "startingSetup" ? currentScope.startingSetupId : startingSetups[0]?.id;
    if (!defaultSetupId) return;
    setValue(
      `keywordNotes.${index}.scope`,
      { kind: "startingSetup", startingSetupId: defaultSetupId },
      { shouldDirty: true },
    );
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-background p-4">
      <div className="flex items-start gap-3">
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor={`keyword-note-${id}-content`}>정보 *</Label>
          {/* 브라우저의 `maxLength` 는 UTF-16 단위로 세어 서버(코드 포인트)와 같거나 더 엄격하다 — 상한을 넘는 정보가
              폼에 생기지 않는다. 카운터도 같은 단위로 센다. */}
          <Textarea
            id={`keyword-note-${id}-content`}
            placeholder="트리거 키워드가 언급되면 참고할 설정 정보를 입력해주세요"
            rows={3}
            maxLength={MAX_KEYWORD_NOTE_CONTENT_LENGTH}
            aria-invalid={!!noteErrors?.content}
            aria-describedby={
              noteErrors?.content
                ? `keyword-note-${id}-content-count keyword-note-${id}-content-error`
                : `keyword-note-${id}-content-count`
            }
            {...register(`keywordNotes.${index}.content`)}
          />
          <p id={`keyword-note-${id}-content-count`} className="self-end text-xs tabular-nums text-muted-foreground">
            {content.length}/{MAX_KEYWORD_NOTE_CONTENT_LENGTH}
          </p>
          <MediaTagOutsideNotice name={`keywordNotes.${index}.content`} />
          {noteErrors?.content && (
            <p id={`keyword-note-${id}-content-error`} role="alert" className="text-xs text-destructive-text">
              {noteErrors.content.message}
            </p>
          )}
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="키워드 노트 삭제" onClick={onRemove}>
          <Trash2 aria-hidden />
        </Button>
      </div>

      <div className="flex flex-col gap-1.5" data-field-path={`keywordNotes.${index}.triggerKeywords`}>
        <Label htmlFor={`keyword-note-${id}-keyword-input`}>트리거 키워드 *</Label>
        <div className="flex gap-2">
          <Input
            id={`keyword-note-${id}-keyword-input`}
            placeholder="트리거 키워드를 입력 후 추가해주세요"
            value={keywordInput}
            aria-invalid={!!keywordRefusal}
            aria-describedby={keywordRefusal ? `keyword-note-${id}-keyword-refusal` : undefined}
            onChange={(event) => {
              setKeywordInput(event.target.value);
              setKeywordRefusal(undefined);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              event.preventDefault();
              addKeyword();
            }}
          />
          <Button type="button" variant="secondary" onClick={addKeyword}>
            추가
          </Button>
        </div>
        {keywordRefusal && (
          <p id={`keyword-note-${id}-keyword-refusal`} role="alert" className="text-xs text-destructive-text">
            {keywordRefusal}
          </p>
        )}
        {triggerKeywords.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {triggerKeywords.map((keyword) => (
              <span
                key={keyword}
                className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground"
              >
                {keyword}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-4"
                  aria-label={`${keyword} 키워드 삭제`}
                  onClick={() => removeKeyword(keyword)}
                >
                  <X aria-hidden className="size-3" />
                </Button>
              </span>
            ))}
          </div>
        )}
        {!!noteErrors?.triggerKeywords?.message && (
          <p id={`keyword-note-${id}-trigger-keywords-error`} role="alert" className="text-xs text-destructive-text">
            {noteErrors.triggerKeywords.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>적용 대상 *</Label>
        <ToggleGroup
          type="single"
          variant="outline"
          value={scope.kind}
          onValueChange={handleScopeKindChange}
          aria-label="적용 대상"
          aria-invalid={!!noteErrors?.scope}
          aria-describedby={noteErrors?.scope ? `keyword-note-${id}-scope-error` : undefined}
        >
          <ToggleGroupItem
            value="global"
            aria-label="스토리 전체"
            className={cn(noteErrors?.scope && "border-destructive ring-3 ring-destructive/20")}
          >
            스토리 전체
          </ToggleGroupItem>
          <ToggleGroupItem
            value="startingSetup"
            aria-label="특정 시작설정"
            disabled={startingSetups.length === 0}
            className={cn(noteErrors?.scope && "border-destructive ring-3 ring-destructive/20")}
          >
            특정 시작설정
          </ToggleGroupItem>
        </ToggleGroup>
        {noteErrors?.scope && (
          <p id={`keyword-note-${id}-scope-error`} role="alert" className="text-xs text-destructive-text">
            {noteErrors.scope.message}
          </p>
        )}

        {scope.kind === "startingSetup" && (
          <ToggleGroup
            type="single"
            variant="outline"
            className="flex-wrap"
            value={scope.startingSetupId}
            onValueChange={(value) =>
              value &&
              setValue(
                `keywordNotes.${index}.scope`,
                { kind: "startingSetup", startingSetupId: value },
                { shouldDirty: true },
              )
            }
            aria-label="적용할 시작설정 선택"
          >
            {startingSetups.map((setup, setupIndex) => (
              <ToggleGroupItem key={setup.id} value={setup.id} aria-label={setup.name || `시작설정 ${setupIndex + 1}`}>
                {setup.name || `시작설정 ${setupIndex + 1}`}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </div>
    </div>
  );
}
