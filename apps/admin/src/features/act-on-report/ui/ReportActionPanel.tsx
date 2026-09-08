import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { useModerationActionMutation } from "@/entities/report";

import {
  PROCESS_OPTIONS,
  reportActionSchema,
  type ProcessAction,
  type ReportActionFormValues,
} from "../model/schema";
import { DeleteConfirmModal } from "./DeleteConfirmModal";

type ReportActionPanelProps = {
  reportId: string;
  reportPending: boolean;
  contentName: string;
  contentRestricted: boolean;
};

const SUCCESS_MESSAGE: Record<ProcessAction, string> = {
  restrict: "이용제한을 부과했어요.",
  delete: "삭제 처리했어요.",
  reject: "반려 처리했어요.",
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

/** techspec-admin.md §1 — US-121이 만든 POST /admin/reports/{id}/action의 첫 FE 소비처.
 *
 * 처리 방식·코멘트는 useState 버퍼가 아니라 RHF+zod가 든다(`apps/web/CLAUDE.md` 폼 규약). 미선택
 * 제출은 zod가 막고 사유를 화면에 남긴다. 코멘트 입력창은 `restrict`/`delete`에서만 나타나므로
 * 그 값은 `useWatch`로 읽는다 — 폼 상태가 단일 소스라 탭을 바꿔도 값이 흩어지지 않는다. */
export function ReportActionPanel({ reportId, reportPending, contentName, contentRestricted }: ReportActionPanelProps) {
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

  if (!reportPending && !contentRestricted) {
    return null;
  }

  async function onSubmit(values: ReportActionFormValues) {
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
    } catch {
      toast.error(ERROR_MESSAGE);
    }
  }

  const handleLiftRestriction = () => {
    moderationAction.mutate(
      { action: "lift-restriction" },
      {
        onSuccess: () => toast.success("이용제한을 해제했어요."),
        onError: () => toast.error(ERROR_MESSAGE),
      },
    );
  };

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold text-foreground">처리</h2>

      {contentRestricted && (
        <div className="flex items-center justify-between gap-3 rounded-lg bg-muted p-3">
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

      {reportPending && (
        <form
          className="flex flex-col gap-3"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit(onSubmit)(event);
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Controller
              control={control}
              name="action"
              render={({ field }) => (
                <ToggleGroup
                  type="single"
                  variant="outline"
                  value={field.value ?? ""}
                  onValueChange={(value) => field.onChange(isProcessAction(value) ? value : undefined)}
                  aria-label="처리 방식 선택"
                  aria-invalid={!!errors.action}
                  aria-describedby={errors.action ? "report-action-error" : undefined}
                  className="w-full"
                >
                  {PROCESS_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value} className="flex-1">
                      {option.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              )}
            />
            {errors.action && (
              <p id="report-action-error" role="alert" className="text-xs text-destructive-text">
                {errors.action.message}
              </p>
            )}
          </div>

          {(action === "restrict" || action === "delete") && (
            <Textarea placeholder="관리자 코멘트 (선택)" rows={3} {...register("adminComment")} />
          )}

          <Button
            type="submit"
            className="self-end aria-disabled:pointer-events-none aria-disabled:opacity-65"
            aria-disabled={moderationAction.isPending}
          >
            {moderationAction.isPending ? "처리 중..." : "처리 확정"}
          </Button>
        </form>
      )}
    </section>
  );
}

/** Radix 토글은 재클릭 시 빈 문자열을 흘려보내고 item value도 `string`이라 좁힘이 필요하다.
 * `as` 대신 술어를 쓰고(TS-03), 화면이 실제로 그리는 목록을 근거로 삼아 둘이 어긋날 수 없게 한다. */
function isProcessAction(value: string): value is ProcessAction {
  return PROCESS_OPTIONS.some((option) => option.value === value);
}
