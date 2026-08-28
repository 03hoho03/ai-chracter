import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { Trash2 } from "lucide-react";
import { useFieldArray, type UseFormReturn } from "react-hook-form";

import type { StoryBuilderFormValues } from "@/features/build-story";

/** techspec-builder-story.md §1.4 — 이름/설명/실행될 프롬프트(전부 필수), 작품 전역 적용이라
 * 스코프 선택 UI가 없다(KeywordNoteTab과 달리 순서/재정렬도 의미가 없어 StatTab과 동일하게
 * add/remove만 지원). */
function ShortcutRow({
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
  const { register } = form;

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-background p-4">
      <div className="flex items-start gap-3">
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor={`shortcut-${id}-name`}>이름 *</Label>
          <Input
            id={`shortcut-${id}-name`}
            placeholder="단축어 이름을 입력해주세요"
            {...register(`shortcuts.${index}.name`)}
          />
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="단축어 삭제" onClick={onRemove}>
          <Trash2 aria-hidden />
        </Button>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`shortcut-${id}-description`}>설명 *</Label>
        <Textarea
          id={`shortcut-${id}-description`}
          placeholder="이 단축어가 어떤 동작을 하는지 설명해주세요"
          rows={2}
          {...register(`shortcuts.${index}.description`)}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`shortcut-${id}-prompt`}>실행될 프롬프트 *</Label>
        <Textarea
          id={`shortcut-${id}-prompt`}
          placeholder="단축어 실행 시 AI에게 전달할 프롬프트를 입력해주세요"
          rows={3}
          {...register(`shortcuts.${index}.prompt`)}
        />
      </div>
    </div>
  );
}

/** techspec-builder-story.md §1.4 AC — 탭 전체가 선택사항(0개도 발행 가능), 작품 전역에 적용되는
 * 단축어 목록을 조회/수정/삭제 가능. */
export function ShortcutTab({ form }: { form: UseFormReturn<StoryBuilderFormValues> }) {
  const { control } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "shortcuts" });

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1">
        <Label>단축어</Label>
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
            <ShortcutRow key={field.id} id={field.id} index={index} form={form} onRemove={() => remove(index)} />
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
            name: "",
            description: "",
            prompt: "",
          })
        }
      >
        단축어 추가
      </Button>
    </div>
  );
}
