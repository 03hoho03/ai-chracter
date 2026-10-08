import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { useForm } from "react-hook-form";

import {
  novelKeys,
  toNovelActionError,
  useUpdateNovelChapterMutation,
  type NovelChapterSummary,
  type NovelChapterUpdateRequest,
  type NovelDetailResponse,
} from "@/entities/novel";

import { createEpisodeTitleSchema, toEpisodeHeading, type EpisodeTitleFormValues } from "../model/schema";

type EpisodeTitleEditorProps = {
  novel: NovelDetailResponse;
  chapter: NovelChapterSummary;
  /** 화 머리(`h2`, `tabIndex=-1`). 호출부가 화를 고를 때 포커스를 보낼 자리다. */
  headingRef?: RefObject<HTMLHeadingElement | null>;
};

/**
 * 편집 패널 화 머리의 제목(`h2 {n}화. {제목}`)과 그 자리 고치기. 연필을 누르면 제목 자리가 입력칸이 되고, 저장·취소·
 * 비우기 뒤에는 제목으로 돌아오며 포커스는 연필로 간다(입력칸이 사라지며 포커스가 `<body>` 로 떨어지지 않게).
 *
 * 고친 제목은 다시 만들기가 덮지 않는다(서버가 고친 시각을 찍는다). AI 가 지은 제목은 다음 다시 만들기가 새로 짓는다는
 * 것을 고치기 전에 한 줄로 알린다. "제목 비우기"는 제목과 고친 표시를 함께 지워, 다음 다시 만들기가 AI 제목을 다시
 * 쓰게 한다 — 그래서 고친 제목이 있을 때만 보인다.
 */
export function EpisodeTitleEditor({ novel, chapter, headingRef }: EpisodeTitleEditorProps) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const errorId = useId();
  const clearNoteId = useId();
  const [isEditing, setIsEditing] = useState(false);
  const [saveError, setSaveError] = useState<string | undefined>(undefined);
  const pencilRef = useRef<HTMLButtonElement>(null);
  const shouldFocusPencilRef = useRef(false);
  const mutation = useUpdateNovelChapterMutation();
  const maxLength = novel.limits.chapterTitleMaxLength;
  const form = useForm<EpisodeTitleFormValues>({
    resolver: zodResolver(createEpisodeTitleSchema(maxLength)),
    defaultValues: { title: chapter.title ?? "" },
  });
  const errorMessage = form.formState.errors.title?.message ?? saveError;
  const isSaving = mutation.isPending;
  const heading = toEpisodeHeading(chapter);

  useEffect(() => {
    if (isEditing || !shouldFocusPencilRef.current) return;
    shouldFocusPencilRef.current = false;
    pencilRef.current?.focus();
  }, [isEditing]);

  function startEditing() {
    form.reset({ title: chapter.title ?? "" });
    setSaveError(undefined);
    setIsEditing(true);
  }

  function finishEditing() {
    shouldFocusPencilRef.current = true;
    setIsEditing(false);
  }

  async function save(body: NovelChapterUpdateRequest) {
    if (isSaving) return;
    setSaveError(undefined);
    try {
      await mutation.mutateAsync({ novelId: novel.id, chapterId: chapter.id, body });
      finishEditing();
    } catch (error) {
      const notice = toNovelActionError(error, "chapterTitle");
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
          void form.handleSubmit((values) => save({ title: values.title.trim() }))(event);
        }}
      >
        {/* 고치는 동안에도 패널의 제목이 남게 한다 — 입력칸이 그 자리를 대신하는 동안 보조기기는 이 줄을 읽는다. */}
        <h2 ref={headingRef} tabIndex={-1} className="sr-only">
          {heading}
        </h2>
        <label htmlFor={inputId} className="text-sm font-medium text-foreground">
          {chapter.ordinal}화 제목
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
            // 패널의 Esc(고르기 해제)까지 올라가지 않게 — 입력을 접는 것으로 끝낸다.
            event.stopPropagation();
            finishEditing();
          }}
          {...form.register("title")}
        />
        {errorMessage !== undefined && (
          <p id={errorId} role="alert" className="text-sm break-keep text-destructive-text">
            {errorMessage}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="secondary" size="sm" aria-disabled={isSaving} className="aria-disabled:opacity-65">
            {isSaving ? "저장 중…" : "저장"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={finishEditing}>
            취소
          </Button>
          {chapter.titleEdited && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-describedby={clearNoteId}
              aria-disabled={isSaving}
              className="aria-disabled:opacity-65"
              onClick={() => void save({ title: null })}
            >
              제목 비우기
            </Button>
          )}
        </div>
        {chapter.titleEdited && (
          <p id={clearNoteId} className="text-xs break-keep text-muted-foreground">
            비우면 다음에 이 화를 다시 만들 때 AI가 제목을 다시 지어요.
          </p>
        )}
      </form>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-1">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className={cn(
            "min-w-0 text-xl font-semibold text-balance break-keep outline-none",
            chapter.title === null ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {heading}
        </h2>
        <Button
          ref={pencilRef}
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={`${chapter.ordinal}화 제목 고치기`}
          className="shrink-0"
          onClick={startEditing}
        >
          <Pencil aria-hidden />
        </Button>
      </div>
      {chapter.title !== null && !chapter.titleEdited && (
        <p className="text-xs break-keep text-muted-foreground">
          AI가 지은 제목이에요. 다시 만들면 새로 지어요 — 고치면 그대로 둬요.
        </p>
      )}
    </div>
  );
}
