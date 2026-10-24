import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, type KeyboardEvent } from "react";
import { useForm, useWatch } from "react-hook-form";

import { BuilderTextarea } from "@/shared/ui/BuilderTextarea";
import { CharacterCount } from "@/shared/ui/CharacterCount";

import { countOutlineChars, OUTLINE_GOAL_MAX_LENGTH, OUTLINE_SUMMARY_MAX_LENGTH, type OutlineEpisodeText } from "../model/outlineEdits";
import { createOutlineEpisodeSchema, type OutlineEpisodeFormValues } from "../model/outlineEpisodeSchema";

type OutlineEpisodeFormProps = {
  /** 화 이름(`3화`). 칸 이름 앞에 붙여 여러 화의 폼이 열린 화면에서도 어느 화의 칸인지 읽힌다. */
  label: string;
  initial: OutlineEpisodeText;
  titleMaxLength: number;
  /** 고친 글을 이 화면의 구성안에 넣는다(서버 저장은 "초안 저장"·"이대로 승인"이 한다). */
  onApply: (text: OutlineEpisodeText) => void;
  onCancel: () => void;
};

/** 구성안 화 하나의 제목·줄거리·목표 고치기. 열리면 제목 칸에 포커스가 가고, `Esc` 는 취소다. */
export function OutlineEpisodeForm({ label, initial, titleMaxLength, onApply, onCancel }: OutlineEpisodeFormProps) {
  const ids = { title: useId(), summary: useId(), goal: useId() };
  const counts = { title: useId(), summary: useId(), goal: useId() };
  const errors = { title: useId(), summary: useId(), goal: useId() };
  const form = useForm<OutlineEpisodeFormValues>({
    resolver: zodResolver(createOutlineEpisodeSchema(titleMaxLength)),
    defaultValues: initial,
  });
  const values = useWatch({ control: form.control });
  const fieldErrors = form.formState.errors;

  function handleKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    onCancel();
  }

  function describedBy(field: keyof OutlineEpisodeFormValues) {
    return fieldErrors[field] === undefined ? counts[field] : `${counts[field]} ${errors[field]}`;
  }

  return (
    <form
      noValidate
      className="flex flex-col gap-4"
      onKeyDown={handleKeyDown}
      onSubmit={(event) => {
        event.preventDefault();
        void form.handleSubmit((submitted) => onApply(submitted))(event);
      }}
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.title}>{label} 제목</Label>
        <Input
          id={ids.title}
          autoFocus
          aria-invalid={fieldErrors.title !== undefined}
          aria-describedby={describedBy("title")}
          {...form.register("title")}
        />
        <CharacterCount id={counts.title} count={countOutlineChars(values.title ?? "")} max={titleMaxLength} />
        <FieldError id={errors.title} message={fieldErrors.title?.message} />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.summary}>{label} 줄거리</Label>
        <BuilderTextarea
          id={ids.summary}
          rows={5}
          aria-invalid={fieldErrors.summary !== undefined}
          aria-describedby={describedBy("summary")}
          {...form.register("summary")}
        />
        <CharacterCount id={counts.summary} count={countOutlineChars(values.summary ?? "")} max={OUTLINE_SUMMARY_MAX_LENGTH} />
        <FieldError id={errors.summary} message={fieldErrors.summary?.message} />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.goal}>{label} 목표</Label>
        <BuilderTextarea
          id={ids.goal}
          rows={2}
          placeholder="이 화가 이야기에서 해낼 일 — 비워도 돼요"
          aria-invalid={fieldErrors.goal !== undefined}
          aria-describedby={describedBy("goal")}
          {...form.register("goal")}
        />
        <CharacterCount id={counts.goal} count={countOutlineChars(values.goal ?? "")} max={OUTLINE_GOAL_MAX_LENGTH} />
        <FieldError id={errors.goal} message={fieldErrors.goal?.message} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="secondary" size="sm">
          적용
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          취소
        </Button>
      </div>
    </form>
  );
}

function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (message === undefined) return null;
  return (
    <p id={id} role="alert" className="text-sm break-keep text-destructive-text">
      {message}
    </p>
  );
}
