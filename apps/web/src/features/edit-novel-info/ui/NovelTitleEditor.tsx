import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { novelKeys, toNovelActionError, type NovelDetailResponse } from "@/entities/novel";

import { useUpdateNovelInfoMutation } from "../api/useUpdateNovelInfoMutation";
import { createTitleFormSchema, type TitleFormValues } from "../model/schema";

/** 작품 정보 화면 머리의 소설 제목(`h1`)과 그 자리 고치기. 연필을 누르면 제목 자리가 입력칸이 되고, 저장하거나
 * 취소하면 다시 제목이 되며 포커스는 연필로 돌아온다(입력칸이 사라지며 포커스가 `<body>` 로 떨어지지 않게).
 *
 * 생성이 지은 제목은 다음 묶음 생성이 다시 지을 수 있다 — 고치기 전에는 그 사실을 제목 아래 한 줄로 알린다. 한 번
 * 고치면 그 뒤로 생성이 제목을 덮지 않는다. */
export function NovelTitleEditor({ novel }: { novel: NovelDetailResponse }) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const errorId = useId();
  const [isEditing, setIsEditing] = useState(false);
  const [saveError, setSaveError] = useState<string | undefined>(undefined);
  const pencilRef = useRef<HTMLButtonElement>(null);
  const shouldFocusPencilRef = useRef(false);
  const mutation = useUpdateNovelInfoMutation();
  const maxLength = novel.limits.titleMaxLength;
  const form = useForm<TitleFormValues>({
    resolver: zodResolver(createTitleFormSchema(maxLength)),
    defaultValues: { title: novel.title ?? "" },
  });
  const fieldError = form.formState.errors.title?.message;
  const errorMessage = fieldError ?? saveError;
  const isSaving = mutation.isPending;

  useEffect(() => {
    if (isEditing || !shouldFocusPencilRef.current) return;
    shouldFocusPencilRef.current = false;
    pencilRef.current?.focus();
  }, [isEditing]);

  function startEditing() {
    form.reset({ title: novel.title ?? "" });
    setSaveError(undefined);
    setIsEditing(true);
  }

  function finishEditing() {
    shouldFocusPencilRef.current = true;
    setIsEditing(false);
  }

  async function handleValidSubmit(values: TitleFormValues) {
    setSaveError(undefined);
    try {
      await mutation.mutateAsync({ novelId: novel.id, body: { title: values.title.trim() } });
      finishEditing();
    } catch (error) {
      const notice = toNovelActionError(error, "title");
      // 재동의가 필요하면 전역 재동의 모달이 맡는다. 입력은 그대로 남아 동의 뒤 다시 저장할 수 있다.
      if (notice === null) return;
      setSaveError(notice.message);
      if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    }
  }

  if (isEditing) {
    return (
      <form
        noValidate
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (isSaving) return;
          void form.handleSubmit(handleValidSubmit)(event);
        }}
      >
        {/* 고치는 동안에도 페이지의 제목이 남게 한다 — 입력칸이 그 자리를 대신하는 동안 보조기기는 이 줄을 읽는다. */}
        <h1 className="sr-only">{novel.title ?? "제목 미정"}</h1>
        <label htmlFor={inputId} className="text-sm font-medium text-foreground">
          소설 제목
        </label>
        <Input
          id={inputId}
          autoFocus
          autoComplete="off"
          aria-invalid={errorMessage !== undefined}
          aria-describedby={errorMessage !== undefined ? errorId : undefined}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            finishEditing();
          }}
          {...form.register("title")}
        />
        {errorMessage !== undefined && (
          <p id={errorId} role="alert" className="text-sm break-keep text-destructive-text">
            {errorMessage}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="secondary" size="sm" aria-disabled={isSaving} className="aria-disabled:opacity-65">
            {isSaving ? "저장 중…" : "저장"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={finishEditing}>
            취소
          </Button>
        </div>
      </form>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-1">
        <h1
          className={cn(
            "min-w-0 text-2xl font-bold tracking-tight text-balance break-keep",
            novel.title === null ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {novel.title ?? "제목 미정"}
        </h1>
        <Button ref={pencilRef} type="button" variant="ghost" size="icon-sm" aria-label="제목 고치기" className="shrink-0" onClick={startEditing}>
          <Pencil aria-hidden />
        </Button>
      </div>
      {novel.title !== null && !novel.titleEdited && (
        <p className="text-xs break-keep text-muted-foreground">자동으로 지은 제목이에요. 고치면 그대로 둬요.</p>
      )}
    </div>
  );
}
