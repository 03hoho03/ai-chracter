import { useId } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@ai-character-chat/ui/components/dialog";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";
import type { z } from "zod";

import type { CommentReportReason } from "@/entities/comment";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { commentReportReasonSchema, commentReportSchema, REASON_OPTIONS } from "../model/reportSchema";

export const CommentReportModal = createCallable<{
  mutationFn: MutationFn<void, CommentReportReason>; onRestoreFocus: () => void;
}, void>(({ call, mutationFn, onRestoreFocus }) => {
  const errorId = useId();
  const form = useForm<z.infer<typeof commentReportSchema>>({ resolver: zodResolver(commentReportSchema) });
  const submit = useMutationFlow(call, mutationFn);
  const isSubmitting = form.formState.isSubmitting || submit.pending;
  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm"
        onCloseAutoFocus={(event) => { event.preventDefault(); requestAnimationFrame(onRestoreFocus); }}>
        <DialogHeader><DialogTitle>댓글 신고</DialogTitle><DialogDescription className="break-keep">이 댓글의 신고 사유를 선택해주세요.</DialogDescription></DialogHeader>
        {/* 폼이 본문과 푸터를 함께 감싸 submit 버튼을 폼 안에 두고, 남은 높이를 받아 그 안에서 본문만 스크롤한다. */}
        <form noValidate onSubmit={(event) => {
          event.preventDefault(); if (!isSubmitting) void form.handleSubmit((values) => submit(values.reason))(event);
        }} className="flex min-h-0 flex-1 flex-col gap-4">
          <DialogBody className="flex flex-col gap-4">
            <Controller control={form.control} name="reason" render={({ field }) => (
              <ToggleGroup type="single" variant="list" orientation="vertical" value={field.value ?? ""}
                onValueChange={(value) => field.onChange(commentReportReasonSchema.options.find((reason) => reason === value))}
                aria-label="신고 사유" aria-invalid={!!form.formState.errors.reason}
                aria-describedby={form.formState.errors.reason ? errorId : undefined} className="w-full">
                {commentReportReasonSchema.options.map((reason) => <ToggleGroupItem key={reason} value={reason} className="h-11 w-full justify-start hover:bg-secondary">{REASON_OPTIONS[reason].label}</ToggleGroupItem>)}
              </ToggleGroup>
            )} />
            {!!form.formState.errors.reason && <p id={errorId} role="alert" className="text-xs text-destructive-text">{form.formState.errors.reason.message}</p>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>취소</Button>
            <Button type="submit" aria-disabled={isSubmitting} className="aria-disabled:opacity-65">{isSubmitting ? "접수 중…" : "신고하기"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
