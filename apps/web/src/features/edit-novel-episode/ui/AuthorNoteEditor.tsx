import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import {
  novelKeys,
  toNovelActionError,
  useUpdateNovelChapterMutation,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";

import { countEpisodeChars, createAuthorNoteSchema, type AuthorNoteFormValues } from "../model/schema";

type AuthorNoteEditorProps = {
  novel: NovelDetailResponse;
  chapter: NovelChapterSummary;
};

/**
 * 화 끝에 붙는 작가의 말과 그 자리 고치기. 읽기 화면에서 본인에게만 보이고 AI 에게는 보내지 않는다 — 그 두 사실을
 * 머리 줄에 적는다. 없으면 "작가의 말 쓰기" 버튼 하나다. 비워서 저장하면 지운다. 저장·취소 뒤 포커스는 그 자리의
 * 연필(또는 쓰기 버튼)로 돌아온다.
 */
export function AuthorNoteEditor({ novel, chapter }: AuthorNoteEditorProps) {
  const queryClient = useQueryClient();
  const headingId = useId();
  const countId = useId();
  const errorId = useId();
  const [isEditing, setIsEditing] = useState(false);
  const [saveError, setSaveError] = useState<string | undefined>(undefined);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const shouldFocusOpenButtonRef = useRef(false);
  const mutation = useUpdateNovelChapterMutation();
  const maxLength = novel.limits.authorNoteMaxLength;
  const form = useForm<AuthorNoteFormValues>({
    resolver: zodResolver(createAuthorNoteSchema(maxLength)),
    defaultValues: { authorNote: chapter.authorNote },
  });
  const authorNote = useWatch({ control: form.control, name: "authorNote" });
  const errorMessage = form.formState.errors.authorNote?.message ?? saveError;
  const isSaving = mutation.isPending;
  const isEmpty = chapter.authorNote === "";

  useEffect(() => {
    if (isEditing || !shouldFocusOpenButtonRef.current) return;
    shouldFocusOpenButtonRef.current = false;
    openButtonRef.current?.focus();
  }, [isEditing]);

  function startEditing() {
    form.reset({ authorNote: chapter.authorNote });
    setSaveError(undefined);
    setIsEditing(true);
  }

  function finishEditing() {
    shouldFocusOpenButtonRef.current = true;
    setIsEditing(false);
  }

  async function handleValidSubmit(values: AuthorNoteFormValues) {
    setSaveError(undefined);
    try {
      await mutation.mutateAsync({
        novelId: novel.id,
        chapterId: chapter.id,
        body: { authorNote: values.authorNote.trim() },
      });
      finishEditing();
    } catch (error) {
      const notice = toNovelActionError(error, "authorNote");
      if (notice === null) return;
      setSaveError(notice.message);
      if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    }
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 id={headingId} className="text-sm font-semibold text-foreground">
          작가의 말 <span className="font-medium text-muted-foreground">· 나만 보여요</span>
        </h3>
        {!isEditing && !isEmpty && (
          <Button
            ref={openButtonRef}
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="작가의 말 고치기"
            onClick={startEditing}
          >
            <Pencil aria-hidden />
          </Button>
        )}
      </div>

      {isEditing && (
        <form
          noValidate
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (isSaving) return;
            void form.handleSubmit(handleValidSubmit)(event);
          }}
        >
          <Textarea
            autoFocus
            aria-labelledby={headingId}
            aria-invalid={errorMessage !== undefined}
            aria-describedby={errorMessage !== undefined ? `${countId} ${errorId}` : countId}
            rows={4}
            placeholder="이 화를 읽은 뒤 나에게 남길 말 — AI에게는 보내지 않아요"
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              event.preventDefault();
              event.stopPropagation();
              finishEditing();
            }}
            {...form.register("authorNote")}
          />
          <p id={countId} className="text-right text-xs text-muted-foreground tabular-nums">
            {countEpisodeChars(authorNote).toLocaleString()} / {maxLength.toLocaleString()}자
          </p>
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
      )}

      {!isEditing && isEmpty && (
        <Button ref={openButtonRef} type="button" variant="outline" size="sm" className="self-start" onClick={startEditing}>
          <Pencil aria-hidden />
          작가의 말 쓰기
        </Button>
      )}
      {!isEditing && !isEmpty && (
        <p className="text-sm whitespace-pre-line text-pretty break-keep text-foreground">{chapter.authorNote}</p>
      )}
    </section>
  );
}
