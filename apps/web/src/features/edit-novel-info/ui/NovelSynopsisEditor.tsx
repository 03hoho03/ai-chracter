import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { novelKeys, toNovelActionError, type NovelDetailResponse } from "@/entities/novel";
import { CharacterCount } from "@/shared/ui/CharacterCount";

import { useUpdateNovelInfoMutation } from "../api/useUpdateNovelInfoMutation";
import { countInfoChars, createSynopsisFormSchema, type SynopsisFormValues } from "../model/schema";

/** 작품 정보 화면의 소개 — 이용자가 적는 글(선택). 제목처럼 그 자리에서 고치고, 비워서 저장하면 소개를 지운다.
 * 저장·취소 뒤 포커스는 연필로 돌아온다. */
export function NovelSynopsisEditor({ novel }: { novel: NovelDetailResponse }) {
  const queryClient = useQueryClient();
  const headingId = useId();
  const countId = useId();
  const errorId = useId();
  const [isEditing, setIsEditing] = useState(false);
  const [saveError, setSaveError] = useState<string | undefined>(undefined);
  const pencilRef = useRef<HTMLButtonElement>(null);
  const shouldFocusPencilRef = useRef(false);
  const mutation = useUpdateNovelInfoMutation();
  const maxLength = novel.limits.synopsisMaxLength;
  const form = useForm<SynopsisFormValues>({
    resolver: zodResolver(createSynopsisFormSchema(maxLength)),
    defaultValues: { synopsis: novel.synopsis },
  });
  const synopsis = useWatch({ control: form.control, name: "synopsis" });
  const fieldError = form.formState.errors.synopsis?.message;
  const errorMessage = fieldError ?? saveError;
  const isSaving = mutation.isPending;

  useEffect(() => {
    if (isEditing || !shouldFocusPencilRef.current) return;
    shouldFocusPencilRef.current = false;
    pencilRef.current?.focus();
  }, [isEditing]);

  function startEditing() {
    form.reset({ synopsis: novel.synopsis });
    setSaveError(undefined);
    setIsEditing(true);
  }

  function finishEditing() {
    shouldFocusPencilRef.current = true;
    setIsEditing(false);
  }

  async function handleValidSubmit(values: SynopsisFormValues) {
    setSaveError(undefined);
    try {
      await mutation.mutateAsync({ novelId: novel.id, body: { synopsis: values.synopsis.trim() } });
      finishEditing();
    } catch (error) {
      const notice = toNovelActionError(error, "synopsis");
      if (notice === null) return;
      setSaveError(notice.message);
      if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    }
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 id={headingId} className="text-lg font-semibold text-foreground">
          소개
        </h2>
        {!isEditing && (
          <Button ref={pencilRef} type="button" variant="ghost" size="icon-sm" aria-label="소개 고치기" onClick={startEditing}>
            <Pencil aria-hidden />
          </Button>
        )}
      </div>

      {isEditing ? (
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
            rows={5}
            placeholder="이 소설이 어떤 이야기인지 짧게 적어주세요"
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              event.preventDefault();
              finishEditing();
            }}
            {...form.register("synopsis")}
          />
          <CharacterCount id={countId} count={countInfoChars(synopsis)} max={maxLength} />
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
      ) : (
        <SynopsisText synopsis={novel.synopsis} />
      )}
    </section>
  );
}

function SynopsisText({ synopsis }: { synopsis: string }) {
  if (synopsis === "") return <p className="text-sm break-keep text-muted-foreground">소개를 적어 두면 여기에 보여요.</p>;
  return <p className="text-sm whitespace-pre-line text-pretty break-keep text-foreground">{synopsis}</p>;
}
