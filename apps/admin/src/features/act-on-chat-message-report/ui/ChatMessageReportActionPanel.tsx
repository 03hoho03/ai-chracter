import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import { REPORT_STATUS_LABELS, type ChatMessageReportDetail } from "@/entities/report";

import { useActOnChatMessageReportMutation } from "../api/useActOnChatMessageReportMutation";
import { chatMessageReportActionSchema, type ChatMessageReportActionValues } from "../model/schema";

type ChatMessageReportAction = ChatMessageReportActionValues["action"];

// 버튼 문구는 처리 후 목록·상세에 보일 상태 이름과 같은 말이다(`resolve` → 처리완료, `reject` → 반려).
const ACTION_LABELS: Record<ChatMessageReportAction, string> = {
  resolve: REPORT_STATUS_LABELS.resolved,
  reject: REPORT_STATUS_LABELS.rejected,
};

const SUCCESS_MESSAGE: Record<ChatMessageReportAction, string> = {
  resolve: "채팅 응답 신고를 처리완료로 바꿨어요.",
  reject: "채팅 응답 신고를 반려했어요.",
};

function isChatMessageReportAction(value: string): value is ChatMessageReportAction {
  return value in ACTION_LABELS;
}

/** 댓글 신고 처리 패널과 같은 모양이되 제재 액션 없이 상태만 바꾼다. BE가 이미 처리된 신고의 재처리를
 * 허용하므로(상태·처리자·시각을 덮어쓰고 감사 로그를 한 줄 더 남긴다) 댓글 신고처럼 패널을 늘 보이고,
 * 처리된 건이면 덮어쓴다는 사실만 알린다. */
export function ChatMessageReportActionPanel({ report }: { report: ChatMessageReportDetail }) {
  const id = useId();
  const mutation = useActOnChatMessageReportMutation(report.id);
  const form = useForm<ChatMessageReportActionValues>({
    resolver: zodResolver(chatMessageReportActionSchema),
    defaultValues: { action: undefined, adminComment: "" },
  });
  const { isSubmitting, errors } = form.formState;

  const onValidSubmit = async (values: ChatMessageReportActionValues) => {
    // 제출 중에도 사유 칸은 편집할 수 있다 — 그사이 새로 적은 내용은 지우지 않는다.
    const submittedComment = form.getValues("adminComment");
    try {
      await mutation.mutateAsync(values);
      toast.success(SUCCESS_MESSAGE[values.action]);
      if (form.getValues("adminComment") === submittedComment) form.setValue("adminComment", "");
    } catch { /* 오류 문구는 폼 안에 띄우고 입력은 그대로 둔다. */ }
  };

  return <section className="flex min-w-0 flex-col gap-4 rounded-xl border border-border bg-card p-2 wrap-anywhere sm:p-6">
    <h2 className="text-lg font-semibold">신고 처리</h2>
    <p className="break-keep text-sm text-muted-foreground">
      신고 상태만 바꿔요. 대화나 작품에는 아무 조치도 하지 않아요.
      {report.status !== "pending" && ` 이미 ${REPORT_STATUS_LABELS[report.status]}된 신고라 다시 저장하면 상태를 덮어쓰고 처리 기록이 한 줄 더 남아요.`}
    </p>
    <form
      noValidate
      className="flex min-w-0 flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (isSubmitting) return;
        void form.handleSubmit(onValidSubmit)(event);
      }}
    >
      <div className="flex flex-col gap-2">
        <Controller control={form.control} name="action" render={({ field }) =>
          <ToggleGroup type="single" variant="outline" value={field.value ?? ""} aria-label="처리 방법" className="max-w-full flex-wrap self-start"
            aria-invalid={!!errors.action} aria-describedby={errors.action ? id + "-action-error" : undefined}
            onValueChange={(value) => { if (isChatMessageReportAction(value)) field.onChange(value); }}>
            <ToggleGroupItem value="resolve" className="h-auto min-h-9 min-w-0 max-w-full whitespace-normal wrap-anywhere">{ACTION_LABELS.resolve}</ToggleGroupItem>
            <ToggleGroupItem value="reject" className="h-auto min-h-9 min-w-0 max-w-full whitespace-normal wrap-anywhere">{ACTION_LABELS.reject}</ToggleGroupItem>
          </ToggleGroup>} />
        {!!errors.action && <p id={id + "-action-error"} role="alert" className="text-xs text-destructive-text">{errors.action.message}</p>}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={id}>처리 사유</Label>
        <Textarea {...form.register("adminComment")} id={id} rows={3} aria-invalid={!!errors.adminComment}
          aria-describedby={errors.adminComment ? id + "-error" : undefined} />
        {!!errors.adminComment && <p id={id + "-error"} role="alert" className="text-xs text-destructive-text">{errors.adminComment.message}</p>}
      </div>
      {mutation.isError && <p role="alert" className="text-sm text-destructive-text">처리를 저장하지 못했어요. 사유는 그대로 남아 있으니 다시 시도해주세요.</p>}
      <Button type="submit" className="h-auto min-h-9 max-w-full self-start whitespace-normal wrap-anywhere aria-disabled:opacity-65" aria-disabled={isSubmitting}>{isSubmitting ? "저장 중…" : "처리 저장"}</Button>
    </form>
  </section>;
}
