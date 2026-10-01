import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import { Smile, X } from "lucide-react";

import { COMMENT_GHOST_HOVER_CLASS_NAME, CommentStickerImage, useCommentStickersQuery, type Comment } from "@/entities/comment";

import { useWriteCommentMutation } from "../api/useWriteCommentMutation";
import type { CommentDraft } from "../model/drafts";
import { commentFormErrors } from "../model/commentFormErrors";
import { commentFormSchema, EMPTY_COMMENT_VALUES, type CommentFormValues } from "../model/schema";
import { CommentLoginModal } from "./CommentLoginModal";
import { CommentTextField } from "./CommentTextField";

type CommentComposerProps = {
  contentId: string; viewerId: string; isLoggedIn: boolean; draft: CommentDraft; canSubmit: boolean;
  disabledReason?: string; editCommentId?: string; replyTarget?: Comment; isReplyMode?: boolean; hasInheritedSpoiler?: boolean; autoFocus?: boolean;
  onChange: (values: CommentFormValues) => void; onSaved: (comment: Comment, requestId: string, isCleared: boolean) => void;
  onCancel?: () => void; canAddMentions?: boolean;
};

export function CommentComposer({
  contentId, viewerId, isLoggedIn, draft, canSubmit, disabledReason, editCommentId, replyTarget,
  isReplyMode, hasInheritedSpoiler, autoFocus, onChange, onSaved, onCancel, canAddMentions = true,
}: CommentComposerProps) {
  const form = useForm<CommentFormValues>({ resolver: zodResolver(commentFormSchema), defaultValues: draft.values });
  const values = useWatch({ control: form.control });
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isSubmittingRef = useRef(false);
  const id = useId();
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const catalog = useCommentStickersQuery();
  const selectedSticker = catalog.data?.items.find((sticker) => sticker.id === values.stickerId);
  const hasInheritedProtection = hasInheritedSpoiler ?? !!replyTarget?.effectiveSpoiler;
  const write = useWriteCommentMutation({ contentId, viewerId, editCommentId, replyTarget, requestId: draft.requestId });
  const { errors, isSubmitting } = form.formState;

  useEffect(() => {
    const subscription = form.watch(() => onChange(form.getValues()));
    return () => subscription.unsubscribe();
  }, [form, onChange]);

  async function handleSubmit(submitted: CommentFormValues) {
    if (isSubmittingRef.current || !canSubmit) return;
    isSubmittingRef.current = true;
    form.clearErrors("root");
    const requestId = draft.requestId;
    try {
      const comment = await write.mutateAsync(submitted);
      const isCleared = JSON.stringify(form.getValues()) === JSON.stringify(submitted);
      if (isCleared) form.reset({ ...EMPTY_COMMENT_VALUES, mentions: [] });
      onSaved(comment, requestId, isCleared);
    } catch (error) {
      for (const failure of commentFormErrors(error)) form.setError(failure.field, { type: "server", message: failure.message });
    }
    finally { isSubmittingRef.current = false; }
  }

  let submitLabel = "댓글 남기기";
  if (isSubmitting) submitLabel = "저장 중…";
  else if (editCommentId) submitLabel = "수정 저장";
  else if (replyTarget) submitLabel = "답글 남기기";

  return (
    <FormProvider {...form}>
      <form noValidate className="flex min-w-0 flex-col gap-3 rounded-lg border border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!isLoggedIn) { void CommentLoginModal.call({ onRestoreFocus: () => inputRef.current?.focus() }); return; }
          if (!canSubmit || isSubmitting || isSubmittingRef.current) return;
          void form.handleSubmit(handleSubmit)(event);
        }}>
        {!!isReplyMode && <div className="flex min-w-0 items-center justify-between gap-2 text-xs text-muted-foreground">
          <span className="break-keep">{replyTarget?.author?.nickname ? replyTarget.author.nickname + "님에게 답글" : "선택한 댓글에 답글"}</span>
          <Button type="button" variant="ghost" className={COMMENT_GHOST_HOVER_CLASS_NAME} size="sm" onClick={onCancel}>답글 취소</Button>
        </div>}
        {(values.mentions ?? []).length > 0 && <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="선택한 멘션"
          aria-invalid={!!errors.mentions} aria-describedby={errors.mentions ? id + "-mentions-error" : undefined}>
          {(values.mentions ?? []).map((author) => (
            <Button type="button" key={author.id} size="sm" variant="secondary"
              aria-label={author.nickname + " 멘션 제거"} onClick={() => form.setValue("mentions", form.getValues("mentions").filter((selected) => selected.id !== author.id), { shouldDirty: true })}>
              @{author.nickname}<X aria-hidden />
            </Button>
          ))}
        </div>}
        <CommentTextField contentId={contentId} viewerId={viewerId} inputRef={inputRef}
          canMention={isLoggedIn && canSubmit && canAddMentions} mentionsErrorId={id + "-mentions-error"} autoFocus={autoFocus} />
        {!!errors.mentions && <p id={id + "-mentions-error"} role="alert" className="text-xs text-destructive-text">{errors.mentions.message}</p>}
        {!!selectedSticker && <div className="flex items-start gap-2">
          <CommentStickerImage sticker={selectedSticker} />
          <Button type="button" variant="ghost" className={COMMENT_GHOST_HOVER_CLASS_NAME} size="icon-sm" aria-label="선택한 스티커 제거"
            onClick={() => form.setValue("stickerId", null, { shouldDirty: true })}><X aria-hidden /></Button>
        </div>}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="outline" size="sm" aria-expanded={isPickerOpen} aria-controls={id + "-stickers"}
            aria-invalid={!!errors.stickerId} aria-describedby={errors.stickerId ? id + "-sticker-error" : undefined}
            onClick={() => setIsPickerOpen((open) => !open)}><Smile aria-hidden />스티커</Button>
          <div className="flex items-center gap-2">
            <Checkbox id={id + "-spoiler"} checked={!!values.isSpoiler || hasInheritedProtection} disabled={hasInheritedProtection}
              aria-invalid={!!errors.isSpoiler} aria-describedby={errors.isSpoiler ? id + "-spoiler-error" : undefined}
              onCheckedChange={(checked) => form.setValue("isSpoiler", checked === true, { shouldDirty: true })} />
            <Label htmlFor={id + "-spoiler"} className="text-xs">스포일러 포함</Label>
          </div>
        </div>
        {hasInheritedProtection && <p className="break-keep text-xs text-muted-foreground">답글 대상의 스포일러 보호를 이어받아요.</p>}
        {!!errors.stickerId && <p id={id + "-sticker-error"} role="alert" className="text-xs text-destructive-text">{errors.stickerId.message}</p>}
        {!!errors.isSpoiler && <p id={id + "-spoiler-error"} role="alert" className="text-xs text-destructive-text">{errors.isSpoiler.message}</p>}
        {isPickerOpen && <div id={id + "-stickers"} className="flex flex-col gap-2">
          <CommentStickerPicker catalog={catalog} selectedId={values.stickerId} onSelect={(stickerId) => {
            form.setValue("stickerId", stickerId, { shouldDirty: true, shouldValidate: true }); setIsPickerOpen(false);
          }} />
        </div>}
        {!!disabledReason && <p className="break-keep text-xs text-muted-foreground">{disabledReason}</p>}
        {!!errors.root && <p role="alert" className="break-keep text-xs text-destructive-text">{errors.root.message}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          {!!editCommentId && <Button type="button" variant="outline" size="sm" onClick={onCancel}>수정 취소</Button>}
          <Button type="submit" size="sm" aria-disabled={isSubmitting || (isLoggedIn && !canSubmit)}
            className="aria-disabled:opacity-65">{submitLabel}</Button>
        </div>
      </form>
    </FormProvider>
  );
}


type CommentStickerPickerProps = {
  catalog: ReturnType<typeof useCommentStickersQuery>; selectedId: string | null | undefined; onSelect: (stickerId: string) => void;
};

function CommentStickerPicker({ catalog, selectedId, onSelect }: CommentStickerPickerProps) {
  const error = <div><p className="text-xs text-destructive-text">스티커를 불러오지 못했어요.</p><Button type="button" variant="outline" size="sm" onClick={() => void catalog.refetch()}>다시 시도</Button></div>;
  if (catalog.isPending) return <p className="text-xs text-muted-foreground">스티커를 불러오는 중…</p>;
  if (catalog.isError && !catalog.data) return error;
  const stickers = catalog.data?.items.filter((sticker) => sticker.isSelectable) ?? [];
  if (catalog.isError && stickers.length === 0) return error;
  if (stickers.length === 0) return <p className="text-xs text-muted-foreground">선택할 수 있는 스티커가 없어요.</p>;
  return <>
    {catalog.isError && error}
    <div role="group" aria-label="공식 스티커 선택" className="grid grid-cols-4 gap-1">
    {stickers.map((sticker) => <button key={sticker.id} type="button" aria-label={sticker.alt} aria-pressed={selectedId === sticker.id}
      className={cn("flex min-w-0 flex-col items-center rounded-lg p-1 text-xs focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring hover:bg-secondary", selectedId === sticker.id && "bg-secondary ring-1 ring-border")}
      onClick={() => onSelect(sticker.id)}>
      <CommentStickerImage sticker={sticker} className="w-14" /><span>{sticker.name}</span>
    </button>)}
    </div>
  </>;
}
