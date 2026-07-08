import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useFieldArray, type UseFormReturn } from "react-hook-form";

import type { CharacterBuilderFormValues } from "../../../features/build-character";

/** techspec-builder-character.md §4 — 인트로는 단일 필드, 예시 대화는 고급설정 뒤에 숨겨진 add/remove 전용
 * 목록(순서가 판정에 영향 없어 dnd-kit 불필요), 플레이가이드는 선택 입력. */
export function IntroTab({ form }: { form: UseFormReturn<CharacterBuilderFormValues> }) {
  const { register, control } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "intro.exampleDialogues" });
  const [showAdvanced, setShowAdvanced] = useState(() => fields.length > 0);

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-intro-first-message">인트로 (첫 대화 본문) *</Label>
        <Textarea
          id="character-intro-first-message"
          placeholder="사용자와의 첫 대화에서 캐릭터가 건넬 말을 입력해주세요"
          rows={4}
          {...register("intro.firstMessage")}
        />
      </div>

      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor="character-intro-advanced-toggle">고급 설정</Label>
          <p className="text-sm text-muted-foreground">예시 대화로 캐릭터의 말투를 보여줄 수 있어요</p>
        </div>
        <Switch
          id="character-intro-advanced-toggle"
          checked={showAdvanced}
          onCheckedChange={setShowAdvanced}
        />
      </div>

      {showAdvanced && (
        <div className="flex flex-col gap-4">
          <Label>예시 대화</Label>
          {fields.map((field, index) => (
            <div key={field.id} className="flex flex-col gap-2 rounded-xl border border-border p-4">
              <div className="flex items-start gap-2">
                <div className="flex flex-1 flex-col gap-2">
                  <Input
                    placeholder="사용자 대사"
                    {...register(`intro.exampleDialogues.${index}.userLine`)}
                  />
                  <Input
                    placeholder="캐릭터 대사"
                    {...register(`intro.exampleDialogues.${index}.characterLine`)}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="예시 대화 삭제"
                  onClick={() => remove(index)}
                >
                  <Trash2 />
                </Button>
              </div>
            </div>
          ))}
          <Button
            type="button"
            variant="secondary"
            onClick={() => append({ id: crypto.randomUUID(), userLine: "", characterLine: "" })}
          >
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
