import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { GripVertical, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useWatch, type UseFormReturn } from "react-hook-form";

import {
  reconcileKeywordNotesOnStartingSetupRemoval,
  type StoryBuilderFormValues,
} from "@/features/build-story";

/** techspec-builder-story.md §1.1 — 이름/프롤로그(필수), 시작상황(선택, 비어있으면 프롤로그가 첫
 * 메시지로 노출됨을 안내), 고급설정 뒤의 플레이가이드/추천 답변(선택). 목록 순서가 곧 기본 선택
 * 우선순위라 dnd-kit로 재정렬한다(AdvancedTab의 situationalImages와 동일 패턴). */
function StartingSetupRow({
  id,
  index,
  form,
  onRemove,
}: {
  id: string;
  index: number;
  form: UseFormReturn<StoryBuilderFormValues>;
  onRemove: () => void;
}) {
  const { register, control, setValue, getValues } = form;
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  const suggestedReplies = useWatch({ control, name: `startingSetups.${index}.suggestedReplies` });
  const [replyInput, setReplyInput] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(
    () =>
      Boolean(getValues(`startingSetups.${index}.playGuide`)) ||
      getValues(`startingSetups.${index}.suggestedReplies`).length > 0,
  );

  function addSuggestedReply() {
    const trimmed = replyInput.trim();
    setReplyInput("");
    if (!trimmed || suggestedReplies.includes(trimmed)) return;
    setValue(`startingSetups.${index}.suggestedReplies`, [...suggestedReplies, trimmed], {
      shouldDirty: true,
    });
  }

  function removeSuggestedReply(reply: string) {
    setValue(
      `startingSetups.${index}.suggestedReplies`,
      suggestedReplies.filter((item) => item !== reply),
      { shouldDirty: true },
    );
  }

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex flex-col gap-4 rounded-xl border border-border bg-background p-4"
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          aria-label="순서 변경"
          className="mt-1.5 cursor-grab touch-none text-muted-foreground hover:text-foreground focus-visible:outline-none"
          {...attributes}
          {...listeners}
        >
          <GripVertical aria-hidden />
        </button>

        <div className="flex flex-1 flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`starting-setup-${id}-name`}>이름 *</Label>
            <Input
              id={`starting-setup-${id}-name`}
              placeholder="시작설정 이름을 입력해주세요"
              {...register(`startingSetups.${index}.name`)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`starting-setup-${id}-prologue`}>프롤로그 *</Label>
            <Textarea
              id={`starting-setup-${id}-prologue`}
              placeholder="이 시작설정의 도입부를 입력해주세요"
              rows={3}
              {...register(`startingSetups.${index}.prologue`)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`starting-setup-${id}-opening-situation`}>시작상황</Label>
            <Textarea
              id={`starting-setup-${id}-opening-situation`}
              placeholder="채팅 시작 시 상황을 입력해주세요"
              rows={2}
              {...register(`startingSetups.${index}.openingSituation`)}
            />
            <p className="text-xs text-muted-foreground">
              비워두면 채팅 시작 시 프롤로그가 첫 메시지로 노출돼요.
            </p>
          </div>
        </div>

        <Button type="button" variant="ghost" size="icon" aria-label="시작설정 삭제" onClick={onRemove}>
          <Trash2 aria-hidden />
        </Button>
      </div>

      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor={`starting-setup-${id}-advanced-toggle`}>고급설정</Label>
          <p className="text-sm text-muted-foreground">플레이가이드와 추천 답변을 추가할 수 있어요</p>
        </div>
        <Switch
          id={`starting-setup-${id}-advanced-toggle`}
          checked={showAdvanced}
          onCheckedChange={setShowAdvanced}
        />
      </div>

      {showAdvanced && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`starting-setup-${id}-play-guide`}>플레이가이드</Label>
            <Textarea
              id={`starting-setup-${id}-play-guide`}
              placeholder="사용자에게 노출할 플레이 안내를 입력해주세요"
              rows={3}
              {...register(`startingSetups.${index}.playGuide`)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`starting-setup-${id}-reply-input`}>추천 답변</Label>
            <div className="flex gap-2">
              <Input
                id={`starting-setup-${id}-reply-input`}
                placeholder="추천 답변을 입력 후 추가해주세요"
                value={replyInput}
                onChange={(event) => setReplyInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") return;
                  event.preventDefault();
                  addSuggestedReply();
                }}
              />
              <Button type="button" variant="secondary" onClick={addSuggestedReply}>
                추가
              </Button>
            </div>
            {suggestedReplies.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {suggestedReplies.map((reply) => (
                  <span
                    key={reply}
                    className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground"
                  >
                    {reply}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-4"
                      aria-label={`${reply} 추천 답변 삭제`}
                      onClick={() => removeSuggestedReply(reply)}
                    >
                      <X aria-hidden className="size-3" />
                    </Button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** techspec-builder-story.md §1.1 AC — "설정 추가"로 여러 시작설정 생성, 발행하려면 최소 1개
 * 필요(발행 버튼 활성화는 StoryBuilderShell의 storyBuilderSchema.safeParse가 이미 담당). */
export function StartingSetupTab({ form }: { form: UseFormReturn<StoryBuilderFormValues> }) {
  const { control, getValues, setValue } = form;
  const { fields, append, remove, move } = useFieldArray({ control, name: "startingSetups" });
  const sensors = useSensors(useSensor(PointerSensor));

  function handleRemove(index: number) {
    const removedId = getValues(`startingSetups.${index}.id`);
    setValue(
      "keywordNotes",
      reconcileKeywordNotesOnStartingSetupRemoval(getValues("keywordNotes"), removedId),
      { shouldDirty: true },
    );
    remove(index);
  }

  function handleDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return;
    const oldIndex = fields.findIndex((field) => field.id === active.id);
    const newIndex = fields.findIndex((field) => field.id === over.id);
    if (oldIndex !== -1 && newIndex !== -1) move(oldIndex, newIndex);
  }

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1">
        <Label>시작설정 *</Label>
        <p className="text-sm text-muted-foreground">
          여러 개의 시작 상황을 만들 수 있어요. 목록의 첫 번째 항목이 기본 선택이에요.
        </p>
      </div>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 시작설정이 없어요.</p>
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-4">
              {fields.map((field, index) => (
                <StartingSetupRow
                  key={field.id}
                  id={field.id}
                  index={index}
                  form={form}
                  onRemove={() => handleRemove(index)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <Button
        type="button"
        variant="secondary"
        className="w-fit"
        onClick={() =>
          append({
            id: crypto.randomUUID(),
            name: "",
            prologue: "",
            openingSituation: "",
            playGuide: "",
            suggestedReplies: [],
            stats: [],
            endings: [],
          })
        }
      >
        설정 추가
      </Button>
    </div>
  );
}
