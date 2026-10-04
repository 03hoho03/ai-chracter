import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { useModerationActionMutation } from "@/entities/report";
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
    defaultValues: { adminComment: "" },
  });

  const moderationAction = useModerationActionMutation(reportId);
  const action = useWatch({ control, name: "action" });

  async function handleValidSubmit(values: ReportActionFormValues) {
    if (moderationAction.isPending) return;

    // 코멘트는 `restrict`/`delete`에서만 입력창이 열린다 — `reject`로 바꿔 제출하면 이전에 적어 둔
    // 값이 남아 있어도 보내지 않는다.
    const adminComment =
      values.action === "reject" || values.adminComment === "" ? undefined : values.adminComment;

    if (values.action === "delete") {
      void DeleteConfirmModal.call({
        contentName,
        mutationFn: async (call) => {
          try {
            await moderationAction.mutateAsync({ action: "delete", adminComment });
            toast.success(SUCCESS_MESSAGE.delete);
            call.end();
            onSuccess?.();
          } catch {
            toast.error(ERROR_MESSAGE);
          }
        },
      });
      return;
    }

    try {
      await moderationAction.mutateAsync({ action: values.action, adminComment });
      toast.success(SUCCESS_MESSAGE[values.action]);
      reset({ adminComment: "" });
      onSuccess?.();
    } catch {
      toast.error(ERROR_MESSAGE);
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
