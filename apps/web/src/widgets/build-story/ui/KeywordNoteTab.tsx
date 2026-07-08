import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Trash2, X } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useWatch, type UseFormReturn } from "react-hook-form";

import type { StartingSetupValues, StoryBuilderFormValues } from "../../../features/build-story";

/** techspec-builder-story.md §1.3 — 정보(필수)/트리거 키워드(필수, 태그 입력)/적용 대상(필수,
 * 스토리 전체 또는 특정 시작설정). 트리거 키워드 칩은 StartingSetupTab의 추천 답변 칩 패턴을,
 * 시작설정 선택은 StatTab의 ToggleGroup 패턴을 재사용한다. */
function KeywordNoteRow({
  id,
  index,
  form,
  startingSetups,
  onRemove,
}: {
  id: string;
  index: number;
  form: UseFormReturn<StoryBuilderFormValues>;
  startingSetups: StartingSetupValues[];
  onRemove: () => void;
}) {
  const { register, control, setValue, getValues } = form;
  const triggerKeywords = useWatch({ control, name: `keywordNotes.${index}.triggerKeywords` });
  const scope = useWatch({ control, name: `keywordNotes.${index}.scope` });
  const [keywordInput, setKeywordInput] = useState("");

  function addKeyword() {
    const trimmed = keywordInput.trim();
    setKeywordInput("");
    if (!trimmed || triggerKeywords.includes(trimmed)) return;
    setValue(`keywordNotes.${index}.triggerKeywords`, [...triggerKeywords, trimmed], { shouldDirty: true });
  }

  function removeKeyword(keyword: string) {
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
          <Textarea
            id={`keyword-note-${id}-content`}
            placeholder="트리거 키워드가 언급되면 참고할 설정 정보를 입력해주세요"
            rows={3}
            {...register(`keywordNotes.${index}.content`)}
          />
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="키워드 노트 삭제" onClick={onRemove}>
          <Trash2 aria-hidden />
        </Button>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`keyword-note-${id}-keyword-input`}>트리거 키워드 *</Label>
        <div className="flex gap-2">
          <Input
            id={`keyword-note-${id}-keyword-input`}
            placeholder="트리거 키워드를 입력 후 추가해주세요"
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
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
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>적용 대상 *</Label>
        <ToggleGroup
          type="single"
          variant="outline"
          value={scope.kind}
          onValueChange={handleScopeKindChange}
          aria-label="적용 대상"
        >
          <ToggleGroupItem value="global" aria-label="스토리 전체">
            스토리 전체
          </ToggleGroupItem>
          <ToggleGroupItem value="startingSetup" aria-label="특정 시작설정" disabled={startingSetups.length === 0}>
            특정 시작설정
          </ToggleGroupItem>
        </ToggleGroup>

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

/** techspec-builder-story.md §1.3 AC — 탭 전체가 선택사항(0개도 발행 가능). */
export function KeywordNoteTab({ form }: { form: UseFormReturn<StoryBuilderFormValues> }) {
  const { control } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "keywordNotes" });
  const startingSetups = useWatch({ control, name: "startingSetups" });

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1">
        <Label>키워드북</Label>
        <p className="text-sm text-muted-foreground">
          특정 단어가 언급되면 자동으로 참고할 설정 정보를 등록해요. 등록하지 않아도 발행할 수 있어요.
        </p>
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
              form={form}
              startingSetups={startingSetups}
              onRemove={() => remove(index)}
            />
          ))}
        </div>
      )}

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
    </div>
  );
}
