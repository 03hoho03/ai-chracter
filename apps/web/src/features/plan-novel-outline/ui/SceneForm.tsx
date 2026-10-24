import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, type KeyboardEvent } from "react";
import { useForm, useWatch } from "react-hook-form";

import { BuilderTextarea } from "@/shared/ui/BuilderTextarea";
import { CharacterCount } from "@/shared/ui/CharacterCount";

import { SCENE_PURPOSE_MAX_LENGTH, SCENE_SUMMARY_MAX_LENGTH, type SceneText } from "../model/episodeScenes";
import { countOutlineChars } from "../model/outlineEdits";
import { createSceneSchema, type SceneFormValues } from "../model/sceneSchema";

type SceneFormProps = {
  /** 장면 이름(`장면 2`). 칸 이름 앞에 붙여 어느 장면의 칸인지 읽힌다. */
  label: string;
  initial: SceneText;
  titleMaxLength: number;
  /** 고친 글을 이 화면의 장면 구성안에 넣는다(서버 저장은 "초안 저장"·"이대로 승인"이 한다). */
  onApply: (text: SceneText) => void;
  onCancel: () => void;
};

/** 장면 하나의 제목·내용·목적 고치기. 열리면 제목 칸에 포커스가 가고, `Esc` 는 취소다. 전체 구성안 화 고치기와 같은 꼴이다. */
export function SceneForm({ label, initial, titleMaxLength, onApply, onCancel }: SceneFormProps) {
  const ids = { title: useId(), summary: useId(), purpose: useId() };
  const counts = { title: useId(), summary: useId(), purpose: useId() };
  const errors = { title: useId(), summary: useId(), purpose: useId() };
  const form = useForm<SceneFormValues>({
    resolver: zodResolver(createSceneSchema(titleMaxLength)),
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

  function describedBy(field: keyof SceneFormValues) {
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
        <Label htmlFor={ids.summary}>{label} 내용</Label>
        <BuilderTextarea
          id={ids.summary}
          rows={4}
          aria-invalid={fieldErrors.summary !== undefined}
          aria-describedby={describedBy("summary")}
          {...form.register("summary")}
        />
        <CharacterCount id={counts.summary} count={countOutlineChars(values.summary ?? "")} max={SCENE_SUMMARY_MAX_LENGTH} />
        <FieldError id={errors.summary} message={fieldErrors.summary?.message} />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.purpose}>{label} 목적</Label>
        <BuilderTextarea
          id={ids.purpose}
          rows={2}
          placeholder="이 장면이 화에서 해낼 일 — 비워도 돼요"
          aria-invalid={fieldErrors.purpose !== undefined}
          aria-describedby={describedBy("purpose")}
          {...form.register("purpose")}
        />
        <CharacterCount id={counts.purpose} count={countOutlineChars(values.purpose ?? "")} max={SCENE_PURPOSE_MAX_LENGTH} />
        <FieldError id={errors.purpose} message={fieldErrors.purpose?.message} />
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
