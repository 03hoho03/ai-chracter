import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import {
  adminNovelKeys,
  isNovelRefundConflict,
  isNovelSalesStopDisabled,
  NOVEL_REFUND_CONFLICT_MESSAGE,
  NOVEL_RESTRICT_REFUND_NOTE,
  NOVEL_SALES_STOP_DISABLED_MESSAGE,
} from "@/entities/admin-novel";
import { reportKeys, useNovelReportActionMutation, type NovelReportDetail } from "@/entities/report";
import { sessionKeys, useSessionQuery } from "@/entities/session";
import { apiErrorCode } from "@/shared/lib/api/client";
import { ActionChoice } from "@/shared/ui/ActionChoice";

import {
  NOVEL_REPORT_ACTION_LABELS,
  novelReportActionSchema,
  type NovelReportActionValues,
} from "../model/schema";

const LINK_CLASS = "admin-hit-area font-medium text-primary hover:underline focus-visible:underline";

const SUCCESS_MESSAGE: Record<NovelReportActionValues["action"], string> = {
  stop_sales: "노벨 판매를 멈추고 신고를 처리했어요.",
  restrict: "노벨을 이용제한하고 신고를 처리했어요.",
  illustration_takedown: "그림 내림으로 신고를 처리했어요.",
  reject: "신고를 반려했어요.",
};

/** 판매 중단을 고르면 확정 전에 산 회원에게 일어날 일을 말한다(이용제한의 환급 문장과 짝). */
const STOP_SALES_NOTE = "판매만 멈춰요. 노벨 목록·홈에서 빠지고 새로 팔지 않아요. 산 회원은 계속 읽고 환급은 없어요.";

/** 지워진 노벨에 조치를 고른 409 의 문장 — 고른 조치에 맞춰 말한다. */
const GONE_MESSAGE: Record<Exclude<NovelReportActionValues["action"], "reject">, string> = {
  restrict: "그사이 노벨이 지워져 이용제한할 대상이 없어요. 반려로 처리해주세요.",
  stop_sales: "그사이 노벨이 지워져 판매를 멈출 대상이 없어요. 반려로 처리해주세요.",
  illustration_takedown: "그사이 노벨이 지워져 그림 내림으로 처리할 대상이 없어요. 반려로 처리해주세요.",
};

/** '삽화 내림으로 처리 완료'를 골랐는데 그 노벨에 내린 그림이 하나도 없을 때(409) — 사유는 그대로 두고 먼저 내리라고 말한다. */
const NOT_TAKEN_DOWN_MESSAGE = "이 노벨에서 내린 그림이 아직 없어요. 노벨 상세에서 그림을 먼저 내려 주세요.";

type NovelReportActionPanelProps = {
  report: NovelReportDetail;
  /** 저장이 성공하면 부른다 — 상세 레이아웃이 시트를 닫는다. */
  onSuccess?: () => void;
};

/** 노벨 신고 처리. 이미 처리된 신고도 다시 처리할 수 있어(상태·처리자·시각을 덮어쓴다) 늘 그린다. 노벨이 지워져 이용제한·판매
 * 중단·그림 내림으로 처리할 대상이 없으면 서버가 409 `NOVEL_GONE` 을 내는데, 응답에 이미 `novelId` 가 비어 있으면 그 처리를 미리 막고 반려만 남긴다 —
 * 409 는 상세를 연 뒤 지워진 경우에만 닿는다. 해제는 신고가 아니라 노벨 상세에서 한다(서버 신고 처리에 해제가 없다). */
export function NovelReportActionPanel({ report, onSuccess }: NovelReportActionPanelProps) {
  const id = useId();
  const queryClient = useQueryClient();
  // 처리를 받지 않은 이유(지워진 노벨·내린 그림 없음) — 고른 처리와 사유 곁에 남겨 운영자가 읽고 바꾸게 한다.
  const [rejectionMessage, setRejectionMessage] = useState<string | null>(null);
  const mutation = useNovelReportActionMutation(report.id, {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
  const isNovelGone = report.novelId === null;
  const form = useForm<NovelReportActionValues>({
    resolver: zodResolver(novelReportActionSchema),
    defaultValues: { action: isNovelGone ? "reject" : undefined, adminComment: "" },
  });
  const { errors, isSubmitting } = form.formState;
  const action = useWatch({ control: form.control, name: "action" });
  const isPolicyOn = useSessionQuery().data?.novelPublicPolicyV2Enabled === true;

  async function handleValidSubmit(values: NovelReportActionValues) {
    setRejectionMessage(null);
    try {
      await mutation.mutateAsync(values);
      toast.success(SUCCESS_MESSAGE[values.action]);
      form.reset({ action: values.action, adminComment: "" });
      onSuccess?.();
    } catch (error) {
      if (apiErrorCode(error) === "NOVEL_GONE" && values.action !== "reject") {
        // 지워진 노벨은 되돌아오지 않는다 — 상세를 새로 읽어 조치를 막고, 반려를 고르게 둔다.
        setRejectionMessage(GONE_MESSAGE[values.action]);
        form.setValue("action", "reject");
        await queryClient.invalidateQueries({ queryKey: reportKeys.all });
        return;
      }
      // 그림 내림으로 닫으려면 그 노벨의 어느 판 그림이든 하나는 내려가 있어야 한다 — 이 화면에 머무는 동안은 고른 처리·
      // 사유를 그대로 둔다(노벨 상세로 옮겨 갔다 돌아오면 패널이 새로 그려져 비어 있다).
      if (apiErrorCode(error) === "NOVEL_ILLUSTRATION_NOT_TAKEN_DOWN") {
        setRejectionMessage(NOT_TAKEN_DOWN_MESSAGE);
        return;
      }
      // 그사이 정책 스위치가 꺼져 판매 중단을 받지 않는다 — 세션을 새로 받아 선택지를 꺼짐 화면으로 돌리고 고른 값을 비운다.
      if (isNovelSalesStopDisabled(error)) {
        toast.error(NOVEL_SALES_STOP_DISABLED_MESSAGE.novelReport);
        form.resetField("action");
        await queryClient.invalidateQueries({ queryKey: sessionKeys.all });
        return;
      }
      // 새 구매자 경합으로 조치 전체가 되돌려졌다 — 사유는 그대로 남아 있어 바로 다시 누르면 된다.
      if (isNovelRefundConflict(error)) {
        toast.error(NOVEL_REFUND_CONFLICT_MESSAGE.novel);
        return;
      }
      toast.error("처리하지 못했어요. 사유는 그대로 남아 있으니 다시 시도해주세요.");
    }
  }

  // 제목·표면은 상세 레이아웃의 조치 열·시트가 진다.
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {/* 신고가 그림 하나 때문이면 노벨 전체를 닫지 않고 그 그림만 내리는 가벼운 길이 있다 — 이 화면에 그 길이 안 보이면
          운영자가 환급이 따르는 이용제한으로만 처리하게 된다. */}
      {report.novelId !== null && (
        <p className="break-keep text-sm text-muted-foreground">
          그림 하나만 내릴 수도 있어요. 문제가 삽화 하나뿐이면{" "}
          <Link to="/novels/$novelId" params={{ novelId: report.novelId }} className={LINK_CLASS}>
            노벨 상세
          </Link>
          의 공개본 화를 펼쳐 그 그림만 내리세요(환급 없음). 지난 판의 그림은 화 펼침에서 판을 골라 내려요. 내린 뒤 이 신고는
          &lsquo;삽화 내림으로 처리 완료&rsquo;로 닫아 주세요.
        </p>
      )}
      {report.novelModerationStatus === "restricted" && (
        <p className="break-keep text-sm text-muted-foreground">
          이 노벨은 이미 이용제한 중이에요. 이용제한을 고르면 신고만 처리완료가 돼요. 해제는 노벨 상세에서 해요.
        </p>
      )}
      {isPolicyOn && report.novelSalesStoppedAt !== null && (
        <p className="break-keep text-sm text-muted-foreground">
          이 노벨은 이미 판매 중단 중이에요. 판매 중단을 고르면 신고만 처리완료가 돼요. 재개는 노벨 상세에서 해요.
        </p>
      )}
      {isNovelGone && (
        <p className="break-keep text-sm text-muted-foreground">노벨이 지워져 조치할 대상이 없어요. 반려만 할 수 있어요.</p>
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
              // 정책 스위치가 켜져 있으면 판매 중단을 첫째로 둔다 — 산 회원의 열람을 남기는 조치를 먼저 보게 한다. 처음
              // 선택은 비워 둔다: 조치와 반려는 신고마다 운영자가 판단하는 일이라 미리 고르면 반려할 신고가 처리될 수 있다.
              options={[
                ...(isPolicyOn
                  ? [{ value: "stop_sales" as const, label: NOVEL_REPORT_ACTION_LABELS.stop_sales, disabled: isNovelGone }]
                  : []),
                { value: "restrict", label: NOVEL_REPORT_ACTION_LABELS.restrict, disabled: isNovelGone },
                {
                  value: "illustration_takedown",
                  label: NOVEL_REPORT_ACTION_LABELS.illustration_takedown,
                  disabled: isNovelGone,
                },
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
        {/* 정책 스위치가 켜져 있으면 이용제한이 이 노벨의 구매를 돌려준다 — 되돌릴 수 없으니 확정 전에 말한다. */}
        {isPolicyOn && action === "restrict" && (
          <p className="text-sm break-keep text-muted-foreground">{NOVEL_RESTRICT_REFUND_NOTE}</p>
        )}
        {isPolicyOn && action === "stop_sales" && (
          <p className="text-sm break-keep text-muted-foreground">{STOP_SALES_NOTE}</p>
        )}
        {!!rejectionMessage && (
          <p role="alert" className="break-keep text-sm text-destructive-text">
            {rejectionMessage}
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
