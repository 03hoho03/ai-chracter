import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import { adminNovelKeys } from "@/entities/admin-novel";
import { reportKeys, useNovelReportActionMutation, type NovelReportDetail } from "@/entities/report";
import { apiErrorCode } from "@/shared/lib/api/client";
import { ActionChoice } from "@/shared/ui/ActionChoice";

import {
  NOVEL_REPORT_ACTION_LABELS,
  novelReportActionSchema,
  type NovelReportActionValues,
} from "../model/schema";

const SUCCESS_MESSAGE = { restrict: "노벨을 이용제한하고 신고를 처리했어요.", reject: "신고를 반려했어요." };

type NovelReportActionPanelProps = {
  report: NovelReportDetail;
  /** 저장이 성공하면 부른다 — 상세 레이아웃이 시트를 닫는다. */
  onSuccess?: () => void;
};

/** 노벨 신고 처리. 이미 처리된 신고도 다시 처리할 수 있어(상태·처리자·시각을 덮어쓴다) 늘 그린다. 노벨이 지워져 이용제한할
 * 대상이 없으면 서버가 409 `NOVEL_GONE` 을 내는데, 응답에 이미 `novelId` 가 비어 있으면 그 처리를 미리 막고 반려만 남긴다 —
 * 409 는 상세를 연 뒤 지워진 경우에만 닿는다. 해제는 신고가 아니라 노벨 상세에서 한다(서버 신고 처리에 해제가 없다). */
export function NovelReportActionPanel({ report, onSuccess }: NovelReportActionPanelProps) {
  const id = useId();
  const queryClient = useQueryClient();
  const [goneMessage, setGoneMessage] = useState<string | null>(null);
  const mutation = useNovelReportActionMutation(report.id, {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
  const isNovelGone = report.novelId === null;
  const form = useForm<NovelReportActionValues>({
    resolver: zodResolver(novelReportActionSchema),
    defaultValues: { action: isNovelGone ? "reject" : undefined, adminComment: "" },
  });
  const { errors, isSubmitting } = form.formState;

  async function handleValidSubmit(values: NovelReportActionValues) {
    setGoneMessage(null);
    try {
      await mutation.mutateAsync(values);
      toast.success(SUCCESS_MESSAGE[values.action]);
      form.reset({ action: values.action, adminComment: "" });
      onSuccess?.();
    } catch (error) {
      if (apiErrorCode(error) === "NOVEL_GONE") {
        // 지워진 노벨은 되돌아오지 않는다 — 상세를 새로 읽어 이용제한을 막고, 반려를 고르게 둔다.
        setGoneMessage("그사이 노벨이 지워져 이용제한할 대상이 없어요. 반려로 처리해주세요.");
        form.setValue("action", "reject");
        await queryClient.invalidateQueries({ queryKey: reportKeys.all });
        return;
      }
      toast.error("처리하지 못했어요. 사유는 그대로 남아 있으니 다시 시도해주세요.");
    }
  }

  // 제목·표면은 상세 레이아웃의 조치 열·시트가 진다.
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {report.novelModerationStatus === "restricted" && (
        <p className="break-keep text-sm text-muted-foreground">
          이 노벨은 이미 이용제한 중이에요. 이용제한을 고르면 신고만 처리완료가 돼요. 해제는 노벨 상세에서 해요.
        </p>
      )}
      {isNovelGone && (
        <p className="break-keep text-sm text-muted-foreground">노벨이 지워져 이용제한할 대상이 없어요. 반려만 할 수 있어요.</p>
      )}
      <form
        noValidate
        className="flex min-w-0 flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (isSubmitting) return;
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
              options={[
                { value: "restrict", label: NOVEL_REPORT_ACTION_LABELS.restrict, disabled: isNovelGone },
                { value: "reject", label: NOVEL_REPORT_ACTION_LABELS.reject },
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
          className="self-end aria-disabled:pointer-events-none aria-disabled:opacity-65"
          aria-disabled={isSubmitting}
        >
          {isSubmitting ? "처리 중..." : "처리 확정"}
        </Button>
      </form>
    </div>
  );
}
