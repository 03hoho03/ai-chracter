import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";

import { useReplyInquiryMutation } from "@/entities/inquiry";

const ERROR_MESSAGE = "답변 등록에 실패했어요. 잠시 후 다시 시도해주세요.";

type Props = {
  inquiryId: string;
  /** 이미 답변한 문의면 기존 답변으로 채워진 채 열린다(오타 수정 경로, techspec.md §6-3). */
  initialReplyBody: string | null;
};

/** `ReportActionPanel` 관용구. 답변은 일반 텍스트라(D-19) 미리보기가 없다 — `Markdown`을 쓰지 않는다. */
export function InquiryReplyPanel({ inquiryId, initialReplyBody }: Props) {
  const [replyBody, setReplyBody] = useState(initialReplyBody ?? "");
  const replyInquiry = useReplyInquiryMutation(inquiryId);

  const handleSubmit = () => {
    const trimmed = replyBody.trim();
    if (!trimmed) return;

    replyInquiry.mutate(
      { replyBody: trimmed },
      {
        onSuccess: () => toast.success("답변을 등록했어요."),
        onError: () => toast.error(ERROR_MESSAGE),
      },
    );
  };

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold text-foreground">답변</h2>

      <Textarea
        value={replyBody}
        onChange={(event) => setReplyBody(event.target.value)}
        placeholder="답변 내용을 입력하세요"
        rows={6}
      />

      <Button
        type="button"
        className="self-end"
        disabled={!replyBody.trim() || replyInquiry.isPending}
        onClick={handleSubmit}
      >
        {replyInquiry.isPending ? "등록 중..." : "답변 등록"}
      </Button>
    </section>
  );
}
