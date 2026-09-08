import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useReplyInquiryMutation } from "@/entities/inquiry";

import { replyInquirySchema, type ReplyInquiryFormValues } from "../model/schema";

type InquiryReplyPanelProps = {
  inquiryId: string;
  /** 이미 답변한 문의면 기존 답변으로 채워진 채 열린다(오타 수정 경로, techspec.md §6-3). */
  initialReplyBody: string | null;
};

const ERROR_MESSAGE = "답변 등록에 실패했어요. 잠시 후 다시 시도해주세요.";

/** `ReportActionPanel` 관용구. 답변은 일반 텍스트라(D-19) 미리보기가 없다 — `Markdown`을 쓰지 않는다.
 *
 * 빈 답변은 컴포넌트 안 수동 검사가 아니라 zod가 막고 사유를 화면에 남긴다(`apps/web/CLAUDE.md` 폼 규약).
 * 등록 중 비활성은 `disabled`가 아니라 `aria-disabled`다 — `disabled`면 누르는 즉시 브라우저가 blur해
 * 키보드 사용자의 포커스가 `<body>`로 떨어진다(`ContentListLoadMore` 선례). `pointer-events`가 못 막는
 * 키보드 Enter는 `onSubmit` 첫 줄 early return이 막는다. */
export function InquiryReplyPanel({ inquiryId, initialReplyBody }: InquiryReplyPanelProps) {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ReplyInquiryFormValues>({
    resolver: zodResolver(replyInquirySchema),
    defaultValues: { replyBody: initialReplyBody ?? "" },
  });

  const replyInquiry = useReplyInquiryMutation(inquiryId);

  async function onSubmit(values: ReplyInquiryFormValues) {
    if (isSubmitting) return;

    try {
      await replyInquiry.mutateAsync(values);
      toast.success("답변을 등록했어요.");
    } catch {
      toast.error(ERROR_MESSAGE);
    }
  }

  return (
    <form
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(onSubmit)(event);
      }}
    >
      <h2 className="text-lg font-semibold text-foreground">답변</h2>

      <div className="flex flex-col gap-1.5">
        <Textarea
          placeholder="답변 내용을 입력하세요"
          rows={6}
          aria-label="답변 내용"
          aria-invalid={!!errors.replyBody}
          aria-describedby={errors.replyBody ? "inquiry-reply-error" : undefined}
          {...register("replyBody")}
        />
        {errors.replyBody && (
          <p id="inquiry-reply-error" role="alert" className="text-xs text-destructive-text">
            {errors.replyBody.message}
          </p>
        )}
      </div>

      <Button
        type="submit"
        className="self-end aria-disabled:pointer-events-none aria-disabled:opacity-65"
        aria-disabled={isSubmitting}
      >
        {isSubmitting ? "등록 중..." : "답변 등록"}
      </Button>
    </form>
  );
}
