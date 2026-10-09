import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useFormContext } from "react-hook-form";

import { MAX_CHARACTER_PROMPT_LENGTH } from "@/entities/content";
import type { CharacterBuilderFormValues } from "@/features/build-character";
import { FieldCharacterCount, useLimitedTextField } from "@/features/build-common";
import { RequiredText } from "@/shared/ui/RequiredText";

import { CharacterMacroNotice } from "./CharacterMacroNotice";

/** 대화 생성에 반영되는 자유 텍스트 캐릭터 프롬프트(필수) 단일 필드. */
export function PromptTab() {
  const form = useFormContext<CharacterBuilderFormValues>();

  const {
    formState: { errors },
  } = form;
  const characterPrompt = useLimitedTextField<CharacterBuilderFormValues>(
    "prompt.characterPrompt",
    MAX_CHARACTER_PROMPT_LENGTH,
  );

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-prompt"><RequiredText>캐릭터 프롬프트</RequiredText></Label>
        <Textarea
          id="character-prompt"
          placeholder="캐릭터의 성격, 말투, 배경 등을 자유롭게 서술해주세요"
          rows={12}
          aria-invalid={!!errors.prompt?.characterPrompt}
          aria-describedby={errors.prompt?.characterPrompt ? "character-prompt-count character-prompt-error" : "character-prompt-count"}
          {...characterPrompt.registration}
        />
        <FieldCharacterCount
          id="character-prompt-count"
          name={characterPrompt.registration.name}
          max={MAX_CHARACTER_PROMPT_LENGTH}
          isTruncated={characterPrompt.isTruncated}
        />
        <CharacterMacroNotice name="prompt.characterPrompt" />
        {errors.prompt?.characterPrompt && (
          <p id="character-prompt-error" role="alert" className="text-xs text-destructive-text">
            {errors.prompt.characterPrompt.message}
          </p>
        )}
      </div>
    </div>
  );
}
