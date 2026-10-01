import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useRef, type FormEvent } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import type { CommentReportDetail } from "@/entities/report";

import { useActOnCommentReportMutation } from "../api/useActOnCommentReportMutation";
import { canResetActionDraft } from "../model/canResetActionDraft";
import { formToServer } from "../model/formToServer";
import { commentReportActionSchema, type CommentReportActionValues } from "../model/schema";

const ACTION_LABELS = { hide: "운영 숨김", restore: "운영 숨김 해제", reject: "신고 반려" };

export function CommentReportActionPanel({ report }: { report: CommentReportDetail }) {
  const id = useId();
  const mutation = useActOnCommentReportMutation(report.id);
  const draftRevisionRef = useRef(0);
  const isSubmittingRef = useRef(false);
  const form = useForm<CommentReportActionValues>({
    resolver: zodResolver(commentReportActionSchema),
    defaultValues: { action: "hide", adminComment: "" },
  });
  const { isSubmitting } = form.formState;

  function handleDraftChange() {
    draftRevisionRef.current += 1;
  }

  async function handleFormSubmit(event: FormEvent<HTMLFormElement>) {
    if (form.formState.isSubmitting || isSubmittingRef.current) {
      event.preventDefault();
      return;
    }
    // 검증 전 원시 입력을 비교한다. 스키마의 trim 결과와 비교하면 그대로인 입력도 변경으로 오인한다.
    const submittedDraft = { ...form.getValues() };
    const submittedRevision = draftRevisionRef.current;
    isSubmittingRef.current = true;
    try {
      await form.handleSubmit(async (values) => {
        try {
          await mutation.mutateAsync(formToServer(values));
          toast.success("댓글 신고 조치를 저장했어요.");
          if (canResetActionDraft(submittedDraft, form.getValues(), submittedRevision, draftRevisionRef.current)) {
            form.reset({ ...submittedDraft, adminComment: "" });
          }
        } catch { /* 오류와 입력은 폼 안에 유지한다. */ }
      })(event);
    } finally {
      isSubmittingRef.current = false;
    }
  }
  return <section className="flex min-w-0 flex-col gap-4 rounded-xl border border-border bg-card p-2 wrap-anywhere sm:p-6">
    <h2 className="text-lg font-semibold">댓글 조치</h2>
    <p className="break-keep text-sm text-muted-foreground">운영 숨김만 변경해요. 작가 숨김은 유지되고 작품 전체의 이용 상태는 바뀌지 않아요. 처리된 신고에서도 운영 숨김을 해제할 수 있어요.</p>
    <form noValidate className="flex min-w-0 flex-col gap-4" onSubmit={(event) => { void handleFormSubmit(event); }}>
      <Controller control={form.control} name="action" render={({ field }) =>
        <ToggleGroup type="single" variant="outline" value={field.value} aria-label="댓글 처리 방법" className="max-w-full flex-wrap"
          onValueChange={(value) => { if (value === "hide" || value === "restore" || value === "reject") { handleDraftChange(); field.onChange(value); } }}>
          <ToggleGroupItem value="hide" className="h-auto min-h-9 min-w-0 max-w-full whitespace-normal wrap-anywhere">{ACTION_LABELS.hide}</ToggleGroupItem>
          <ToggleGroupItem value="restore" className="h-auto min-h-9 min-w-0 max-w-full whitespace-normal wrap-anywhere" disabled={!report.comment.moderatorHidden || (!!report.comment.deletedAt && report.comment.rootCommentId !== null)}>{ACTION_LABELS.restore}</ToggleGroupItem>
          <ToggleGroupItem value="reject" className="h-auto min-h-9 min-w-0 max-w-full whitespace-normal wrap-anywhere">{ACTION_LABELS.reject}</ToggleGroupItem>
        </ToggleGroup>} />
      {!!report.comment.deletedAt && <p className="text-xs text-muted-foreground">{report.comment.rootCommentId === null
        ? "삭제한 원문은 복원하지 않아요. 운영 숨김만 해제하며 남은 답글의 별도 숨김은 유지돼요."
        : "삭제한 대댓글의 원문과 숨김은 복원할 수 없어요."}</p>}
      <div className="flex flex-col gap-2">
        <Label htmlFor={id}>조치 사유</Label>
        <Textarea {...form.register("adminComment")} onChangeCapture={handleDraftChange} id={id} rows={3} aria-invalid={!!form.formState.errors.adminComment}
          aria-describedby={form.formState.errors.adminComment ? id + "-error" : undefined} />
        {!!form.formState.errors.adminComment && <p id={id + "-error"} role="alert" className="text-xs text-destructive-text">{form.formState.errors.adminComment.message}</p>}
      </div>
      {mutation.isError && <p role="alert" className="text-sm text-destructive-text">조치를 저장하지 못했어요. 사유는 그대로 남아 있으니 다시 시도해주세요.</p>}
      <Button type="submit" className="h-auto min-h-9 max-w-full self-start whitespace-normal wrap-anywhere aria-disabled:opacity-65" aria-disabled={isSubmitting}>{isSubmitting ? "저장 중…" : "조치 저장"}</Button>
    </form>
  </section>;
}
