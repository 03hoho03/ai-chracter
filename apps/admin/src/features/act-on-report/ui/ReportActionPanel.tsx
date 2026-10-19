import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import {
  DERIVATIVE_NOVELS_DEFAULT,
  DERIVATIVE_NOVELS_LEGEND,
  DERIVATIVE_NOVELS_NOTE,
  DERIVATIVE_NOVELS_OPTIONS,
  isNovelRefundConflict,
  isNovelSalesStopDisabled,
  NOVEL_REFUND_CONFLICT_MESSAGE,
  NOVEL_SALES_STOP_DISABLED_MESSAGE,
  toDerivativeNovelsField,
} from "@/entities/admin-novel";
import { useModerationActionMutation } from "@/entities/report";
import { sessionKeys, useSessionQuery } from "@/entities/session";
import { ActionChoice, type ActionChoiceOption } from "@/shared/ui/ActionChoice";

import {
  PROCESS_OPTIONS,
  reportActionSchema,
  type ProcessAction,
  type ReportActionFormValues,
} from "../model/schema";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import { LiftRestrictionConfirmModal } from "./LiftRestrictionConfirmModal";

type ReportActionPanelProps = {
  reportId: string;
  isReportPending: boolean;
  contentName: string;
  isContentRestricted: boolean;
  /** 처리가 성공하면(확인 모달이 있으면 모달이 닫힌 뒤) 부른다 — 상세 레이아웃이 시트를 닫는다. */
  onSuccess?: () => void;
};

/** 대기 중인 신고는 처리할 수 있고, 처리된 신고라도 작품이 이용제한 중이면 해제할 수 있다. 둘 다 아니면 조치가 없다 —
 * 상세 레이아웃이 조치 열·하단 바를 그릴지 패널을 그리기 전에 알아야 해서 패널 밖 판정으로 둔다. */
export function canActOnContentReport({
  isReportPending,
  isContentRestricted,
}: Pick<ReportActionPanelProps, "isReportPending" | "isContentRestricted">) {
  return isReportPending || isContentRestricted;
}

/** 삭제는 되돌릴 수 없어 형태(아이콘·destructive 틴트)로도 갈리고, 목록 맨 끝에 둔다 — 두 일반 처리 사이에 끼면
 * 옆 항목을 고르려다 잘못 누르기 쉽다. */
const PROCESS_CHOICES: ActionChoiceOption<ProcessAction>[] = [
  ...PROCESS_OPTIONS.filter((option) => option.value !== "delete"),
  ...PROCESS_OPTIONS.filter((option) => option.value === "delete").map(
    (option): ActionChoiceOption<ProcessAction> => ({ ...option, tone: "destructive" }),
  ),
];

const SUCCESS_MESSAGE: Record<ProcessAction, string> = {
  restrict: "이용제한을 부과했어요.",
  delete: "삭제 처리했어요.",
  reject: "반려 처리했어요.",
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

/** 이용제한·삭제 실패 문장. 그 작품으로 만든 노벨의 새 구매자 경합으로 조치 전체가 되돌려졌으면 다시 누르라고 하고,
 * 판매 중단을 골랐는데 그사이 정책 스위치가 꺼졌으면 그렇게 말한다(호출부가 세션을 새로 받는다). */
function toProcessErrorMessage(error: unknown): string {
  if (isNovelSalesStopDisabled(error)) return NOVEL_SALES_STOP_DISABLED_MESSAGE.content;
  return isNovelRefundConflict(error) ? NOVEL_REFUND_CONFLICT_MESSAGE.content : ERROR_MESSAGE;
}

/** POST /admin/reports/{id}/action의 첫 FE 소비처.
 *
 * 처리 방식·코멘트는 useState 버퍼가 아니라 RHF+zod가 든다(`apps/web/CLAUDE.md` 폼 규약). 미선택
 * 제출은 zod가 막고 사유를 화면에 남긴다. 코멘트 입력창은 `restrict`/`delete`에서만 나타나므로
 * 그 값은 `useWatch`로 읽는다 — 폼 상태가 단일 소스라 탭을 바꿔도 값이 흩어지지 않는다. */
export function ReportActionPanel({
  reportId,
  isReportPending,
  contentName,
  isContentRestricted,
  onSuccess,
}: ReportActionPanelProps) {
  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ReportActionFormValues>({
    resolver: zodResolver(reportActionSchema),
    defaultValues: { adminComment: "", derivativeNovels: DERIVATIVE_NOVELS_DEFAULT },
  });
  const queryClient = useQueryClient();

  const moderationAction = useModerationActionMutation(reportId);
  const action = useWatch({ control, name: "action" });
  const derivativeNovelsChoice = useWatch({ control, name: "derivativeNovels" });
  const isPolicyOn = useSessionQuery().data?.novelPublicPolicyV2Enabled === true;
  const isClosing = action === "restrict" || action === "delete";

  /** 실패를 알리고, 스위치가 꺼져 판매 중단이 거부됐으면 세션을 새로 받아 고르는 칸을 꺼짐 화면으로 돌린다. */
  function handleProcessError(error: unknown) {
    toast.error(toProcessErrorMessage(error));
    if (isNovelSalesStopDisabled(error)) void queryClient.invalidateQueries({ queryKey: sessionKeys.all });
  }

  async function handleValidSubmit(values: ReportActionFormValues) {
    if (moderationAction.isPending) return;

    // 코멘트는 `restrict`/`delete`에서만 입력창이 열린다 — `reject`로 바꿔 제출하면 이전에 적어 둔
    // 값이 남아 있어도 보내지 않는다.
    const adminComment =
      values.action === "reject" || values.adminComment === "" ? undefined : values.adminComment;
    const derivativeNovels = toDerivativeNovelsField(
      isPolicyOn,
      values.action === "restrict" || values.action === "delete",
      values.derivativeNovels,
    );

    if (values.action === "delete") {
      void DeleteConfirmModal.call({
        contentName,
        mutationFn: async (call) => {
          try {
            await moderationAction.mutateAsync({ action: "delete", adminComment, derivativeNovels });
            toast.success(SUCCESS_MESSAGE.delete);
            call.end();
            onSuccess?.();
          } catch (error) {
            handleProcessError(error);
            // 스위치가 꺼졌으면 고른 값이 뜻을 잃었다 — 확인 모달을 닫아 패널의 바뀐 설명을 보고 다시 고르게 한다.
            if (isNovelSalesStopDisabled(error)) call.end();
          }
        },
      });
      return;
    }

    try {
      await moderationAction.mutateAsync({ action: values.action, adminComment, derivativeNovels });
      toast.success(SUCCESS_MESSAGE[values.action]);
      reset({ adminComment: "", derivativeNovels: DERIVATIVE_NOVELS_DEFAULT });
      onSuccess?.();
    } catch (error) {
      handleProcessError(error);
    }
  }

  // 대화방 일괄 전환이 되돌릴 수 없어 확인 모달을 거친다.
  const handleLiftRestriction = () => {
    void LiftRestrictionConfirmModal.call({
      contentName,
      isReportPending,
      mutationFn: async (call) => {
        try {
          await moderationAction.mutateAsync({ action: "lift-restriction" });
          toast.success("이용제한을 해제했어요.");
          call.end();
          onSuccess?.();
        } catch {
          toast.error(ERROR_MESSAGE);
        }
      },
    });
  };

  // 제목·표면은 상세 레이아웃의 조치 열·시트가 진다.
  return (
    <div className="flex flex-col gap-4">
      {isContentRestricted && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3">
          <p className="text-sm text-muted-foreground">현재 이용제한 상태입니다.</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={moderationAction.isPending}
            onClick={handleLiftRestriction}
          >
            이용제한 해제
          </Button>
        </div>
      )}

      {isReportPending && (
        <form
          className="flex flex-col gap-3"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit(handleValidSubmit)(event);
          }}
        >
          <Controller
            control={control}
            name="action"
            render={({ field }) => (
              <ActionChoice
                legend="처리 방법"
                options={PROCESS_CHOICES}
                value={field.value}
                onValueChange={field.onChange}
                error={errors.action?.message}
              />
            )}
          />

          {(action === "restrict" || action === "delete") && (
            <Textarea placeholder="관리자 코멘트 (선택)" aria-label="관리자 코멘트 (선택)" rows={3} {...register("adminComment")} />
          )}

          {/* 정책 스위치가 켜져 있으면 이용제한·삭제가 이 작품으로 만든 노벨을 어떻게 할지 고른다 — 처음 값은 판매 중단이고,
              환급 문장은 닫기를 골랐을 때만 나온다. 삭제는 확인 모달로 가기 전에 여기서 고른 값을 넘긴다. */}
          {isPolicyOn && isClosing && (
            <div className="flex flex-col gap-1.5">
              <Controller
                control={control}
                name="derivativeNovels"
                render={({ field }) => (
                  <ActionChoice
                    legend={DERIVATIVE_NOVELS_LEGEND}
                    options={DERIVATIVE_NOVELS_OPTIONS}
                    value={field.value}
                    onValueChange={field.onChange}
                  />
                )}
              />
              <p className="text-sm break-keep text-muted-foreground">{DERIVATIVE_NOVELS_NOTE[derivativeNovelsChoice]}</p>
            </div>
          )}

          {/* 삭제를 고르면 확정 버튼도 destructive 틴트로 바뀐다 — 솔리드 레드 채움은 이 시스템에 없다. */}
          <Button
            type="submit"
            variant={action === "delete" ? "destructive" : "default"}
            className="self-end aria-disabled:pointer-events-none aria-disabled:opacity-65"
            aria-disabled={moderationAction.isPending}
          >
            {moderationAction.isPending ? "처리 중..." : "처리 확정"}
          </Button>
        </form>
      )}
    </div>
  );
}
