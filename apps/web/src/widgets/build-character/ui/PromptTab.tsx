import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import type { UseFormReturn } from "react-hook-form";

import type { CharacterBuilderFormValues } from "@/features/build-character";

/** techspec-builder-character.md §3 — 대화 생성에 반영되는 자유 텍스트 캐릭터 프롬프트(필수) 단일 필드. */
export function PromptTab({ form }: { form: UseFormReturn<CharacterBuilderFormValues> }) {
  const { register } = form;

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-prompt">캐릭터 프롬프트 *</Label>
        <Textarea
          id="character-prompt"
          placeholder="캐릭터의 성격, 말투, 배경 등을 자유롭게 서술해주세요"
          rows={12}
          {...register("prompt.characterPrompt")}
        />
      </div>
    </div>
  );
}
