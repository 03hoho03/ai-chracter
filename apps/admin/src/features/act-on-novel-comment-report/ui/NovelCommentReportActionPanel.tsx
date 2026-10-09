import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { adminNovelKeys } from "@/entities/admin-novel";
import { reportKeys, useNovelCommentReportActionMutation, type NovelCommentReportDetail } from "@/entities/report";
import { apiErrorCode } from "@/shared/lib/api/client";
import { ActionChoice } from "@/shared/ui/ActionChoice";

import {
  NOVEL_COMMENT_REPORT_ACTION_LABELS,
  novelCommentReportActionSchema,
  type NovelCommentReportActionValues,
} from "../model/schema";
import { NovelCommentDeleteConfirmModal } from "./NovelCommentDeleteConfirmModal";

const SUCCESS_MESSAGE = {
  hide: "댓글을 숨기고 신고를 처리했어요.",
  delete: "댓글을 지우고 신고를 처리했어요.",
  reject: "신고를 반려했어요.",
};

/** 상세를 연 뒤 댓글 상태가 바뀐 409 — 숨김·삭제는 막히고 반려만 남는다. */
const GONE_MESSAGES: Record<string, string> = {
  NOVEL_COMMENT_GONE: "그사이 댓글이 사라졌어요(작성자 탈퇴·소설 삭제). 반려로 처리해주세요.",
  NOVEL_COMMENT_DELETED: "그사이 댓글이 지워졌어요. 반려로 처리해주세요.",
};

type NovelCommentReportActionPanelProps = {
  report: NovelCommentReportDetail;
  /** 저장이 성공하면(삭제는 확인 모달이 닫힌 뒤) 부른다 — 상세 레이아웃이 시트를 닫는다. */
  onSuccess?: () => void;
};

/** 노벨 댓글 신고 처리. 이미 처리된 신고도 다시 처리할 수 있어 늘 그린다. 댓글이 이미 사라졌거나 지워졌으면 숨김·삭제를 미리
 * 막고 반려만 남긴다 — 서버의 409 는 상세를 연 뒤에 바뀐 경우에만 닿는다. 숨김 해제는 신고가 아니라 노벨 상세 댓글 목록에서
 * 한다(서버 신고 처리에 해제가 없다). 삭제는 되돌릴 수 없어 확인 모달을 한 번 더 거친다. */
export function NovelCommentReportActionPanel({ report, onSuccess }: NovelCommentReportActionPanelProps) {
  const id = useId();
  const queryClient = useQueryClient();
  const [goneMessage, setGoneMessage] = useState<string | null>(null);
  const mutation = useNovelCommentReportActionMutation(report.id, {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
  const isCommentUnavailable = report.comment === null || report.comment.deletedAt !== null;
  const form = useForm<NovelCommentReportActionValues>({
    resolver: zodResolver(novelCommentReportActionSchema),
    defaultValues: { action: isCommentUnavailable ? "reject" : undefined, adminComment: "" },
  });
  const { errors, isSubmitting } = form.formState;
  const action = useWatch({ control: form.control, name: "action" });

  async function submit(values: NovelCommentReportActionValues) {
    setGoneMessage(null);
    try {
      await mutation.mutateAsync(values);
      toast.success(SUCCESS_MESSAGE[values.action]);
      form.reset({ action: values.action === "delete" ? "reject" : values.action, adminComment: "" });
      return true;
    } catch (error) {
      const code = apiErrorCode(error);
      const gone = code === null ? undefined : GONE_MESSAGES[code];
      if (gone) {
        setGoneMessage(gone);
        form.setValue("action", "reject");
        await queryClient.invalidateQueries({ queryKey: reportKeys.all });
        return false;
      }
      toast.error("처리하지 못했어요. 사유는 그대로 남아 있으니 다시 시도해주세요.");
      return false;
    }
  }

  async function handleValidSubmit(values: NovelCommentReportActionValues) {
    if (values.action !== "delete") {
      if (await submit(values)) onSuccess?.();
      return;
    }
    void NovelCommentDeleteConfirmModal.call({
      mutationFn: async (call) => {
        const isDone = await submit(values);
        call.end();
        if (isDone) onSuccess?.();
      },
    });
  }

  // 제목·표면은 상세 레이아웃의 조치 열·시트가 진다.
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {isCommentUnavailable && (
        <p className="break-keep text-sm text-muted-foreground">
          댓글이 이미 지워졌거나 사라져 숨김·삭제할 대상이 없어요. 반려만 할 수 있어요.
        </p>
      )}
      {!isCommentUnavailable && report.comment?.moderatorHidden && (
        <p className="break-keep text-sm text-muted-foreground">
          이미 운영 숨김 중인 댓글이에요. 숨김 해제는 노벨 상세의 댓글 목록에서 해요.
        </p>
      )}
      <form
        noValidate
        className="flex min-w-0 flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (isSubmitting || mutation.isPending) return;
          void form.handleSubmit(handleValidSubmit)(event);
        }}
      >
        <Controller
          control={form.control}
          name="action"
          render={({ field }) => (
            <ActionChoice
              legend="처리 방법"
              value={field.value}
              onValueChange={field.onChange}
              error={errors.action?.message}
              // 삭제는 되돌릴 수 없어 형태로도 갈리고 목록 맨 끝에 둔다 — 두 일반 처리 사이에 끼면 잘못 누르기 쉽다.
              options={[
                { value: "hide", label: NOVEL_COMMENT_REPORT_ACTION_LABELS.hide, disabled: isCommentUnavailable },
                { value: "reject", label: NOVEL_COMMENT_REPORT_ACTION_LABELS.reject },
                {
                  value: "delete",
                  label: NOVEL_COMMENT_REPORT_ACTION_LABELS.delete,
                  tone: "destructive",
                  disabled: isCommentUnavailable,
                },
              ]}
            />
          )}
        />
        <div className="flex flex-col gap-2">
          <Label htmlFor={id}>조치 사유</Label>
          <Textarea
            {...form.register("adminComment")}
            id={id}
            rows={3}
            placeholder="감사 로그에 남길 사유"
            aria-invalid={!!errors.adminComment}
            aria-describedby={errors.adminComment ? `${id}-error` : undefined}
          />
          {!!errors.adminComment && (
            <p id={`${id}-error`} role="alert" className="text-xs text-destructive-text">
              {errors.adminComment.message}
            </p>
          )}
        </div>
        {!!goneMessage && (
          <p role="alert" className="break-keep text-sm text-destructive-text">
            {goneMessage}
          </p>
        )}
        <Button
          type="submit"
          variant={action === "delete" ? "destructive" : "default"}
          className="self-end aria-disabled:pointer-events-none aria-disabled:opacity-65"
          aria-disabled={isSubmitting || mutation.isPending}
        >
          {mutation.isPending ? "처리 중..." : "처리 확정"}
        </Button>
      </form>
    </div>
  );
}
