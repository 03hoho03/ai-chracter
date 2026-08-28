import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";

import { useModerationActionMutation, type ModerationActionType } from "@/entities/report";
import { DeleteConfirmModal } from "./DeleteConfirmModal";

type ProcessAction = Extract<ModerationActionType, "restrict" | "delete" | "reject">;

const PROCESS_OPTIONS: { value: ProcessAction; label: string }[] = [
  { value: "restrict", label: "이용제한 부과" },
  { value: "delete", label: "삭제" },
  { value: "reject", label: "조치 없음(반려)" },
];

/** Radix 토글은 재클릭 시 빈 문자열을 흘려보내고 item value도 `string`이라 좁힘이 필요하다.
 * `as` 대신 술어를 쓰고(TS-03), 화면이 실제로 그리는 목록을 근거로 삼아 둘이 어긋날 수 없게 한다. */
function isProcessAction(value: string): value is ProcessAction {
  return PROCESS_OPTIONS.some((option) => option.value === value);
}

const SUCCESS_MESSAGE: Record<ProcessAction, string> = {
  restrict: "이용제한을 부과했어요.",
  delete: "삭제 처리했어요.",
  reject: "반려 처리했어요.",
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

type Props = {
  reportId: string;
  reportPending: boolean;
  contentName: string;
  contentRestricted: boolean;
};

/** techspec-admin.md §1 — US-121이 만든 POST /admin/reports/{id}/action의 첫 FE 소비처. */
export function ReportActionPanel({ reportId, reportPending, contentName, contentRestricted }: Props) {
  const [action, setAction] = useState<ProcessAction>();
  const [adminComment, setAdminComment] = useState("");
  const moderationAction = useModerationActionMutation(reportId);

  if (!reportPending && !contentRestricted) {
    return null;
  }

  const handleProcess = () => {
    if (!action) return;

    if (action === "delete") {
      void DeleteConfirmModal.call({
        contentName,
        mutationFn: async (call) => {
          try {
            await moderationAction.mutateAsync({ action: "delete", adminComment: adminComment.trim() || undefined });
            toast.success(SUCCESS_MESSAGE.delete);
            call.end();
          } catch {
            toast.error(ERROR_MESSAGE);
          }
        },
      });
      return;
    }

    moderationAction.mutate(
      { action, adminComment: action === "restrict" ? adminComment.trim() || undefined : undefined },
      {
        onSuccess: () => {
          toast.success(SUCCESS_MESSAGE[action]);
          setAction(undefined);
          setAdminComment("");
        },
        onError: () => toast.error(ERROR_MESSAGE),
      },
    );
  };

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
        <div className="flex flex-col gap-3">
          <ToggleGroup
            type="single"
            variant="outline"
            value={action ?? ""}
            onValueChange={(value) => setAction(isProcessAction(value) ? value : undefined)}
            aria-label="처리 방식 선택"
            className="w-full"
          >
            {PROCESS_OPTIONS.map((option) => (
              <ToggleGroupItem key={option.value} value={option.value} className="flex-1">
                {option.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>

          {(action === "restrict" || action === "delete") && (
            <Textarea
              value={adminComment}
              onChange={(event) => setAdminComment(event.target.value)}
              placeholder="관리자 코멘트 (선택)"
              rows={3}
            />
          )}

          <Button
            type="button"
            className="self-end"
            disabled={!action || moderationAction.isPending}
            onClick={handleProcess}
          >
            {moderationAction.isPending ? "처리 중..." : "처리 확정"}
          </Button>
        </div>
      )}
    </section>
  );
}
