import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { useFormContext } from "react-hook-form";

import type { PromptSetFormValues } from "../model/schema";

type LabelFieldKey = keyof PromptSetFormValues["labels"];

const LABEL_FIELDS: { key: LabelFieldKey; id: string; title: string; hint: string }[] = [
  {
    key: "userLabel",
    id: "prompt-label-user",
    title: "사용자 라벨",
    hint: "대화 로그에서 사용자 턴 앞에 붙는 이름. stop_sequence가 이 값에서 파생돼요.",
  },
  {
    key: "storyAssistantLabel",
    id: "prompt-label-story-assistant",
    title: "스토리 진행자 라벨",
    hint: "스토리 챗에서 진행자(AI) 턴 앞에 붙는 이름.",
  },
  {
    key: "storyExampleLabel",
    id: "prompt-label-story-example",
    title: "스토리 전개 예시 라벨",
    hint: "전개 예시 안에서 진행자 역할을 부르는 이름(진행자 라벨과 다를 수 있어요).",
  },
  {
    key: "characterAssistantLabel",
    id: "prompt-label-character-assistant",
    title: "캐릭터 라벨",
    hint: "캐릭터 챗에서 캐릭터(AI) 턴 앞에 붙는 이름.",
  },
];

/** 화자 라벨 4개 — 전부 stop_sequence 파생(§4-5)이나 전개 예시 조립에 쓰이므로 개행·':'을
 * 포함할 수 없다(R-5, zod가 `model/schema.ts`에서 먼저 막는다). */
export function LabelsCard() {
  const {
    register,
    formState: { errors },
  } = useFormContext<PromptSetFormValues>();

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4">
      <h2 className="text-lg font-semibold text-foreground">화자 라벨</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {LABEL_FIELDS.map((field) => {
          const error = errors.labels?.[field.key];
          return (
            <div key={field.id} className="flex flex-col gap-1.5">
              <Label htmlFor={field.id}>{field.title}</Label>
              <Input
                id={field.id}
                aria-invalid={!!error}
                aria-describedby={`${field.id}-hint${error ? ` ${field.id}-error` : ""}`}
                {...register(`labels.${field.key}`)}
              />
              {error ? (
                <p id={`${field.id}-error`} role="alert" className="text-xs text-destructive-text">
                  {error.message}
                </p>
              ) : (
                <p id={`${field.id}-hint`} className="break-keep text-xs text-muted-foreground">
                  {field.hint}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
