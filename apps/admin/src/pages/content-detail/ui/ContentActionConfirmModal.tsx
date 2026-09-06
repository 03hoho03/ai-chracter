import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { createCallable } from "react-call";
import { toast } from "sonner";

import {
  REASON_CATEGORY_LABELS,
  useContentActionMutation,
  type AdminContentActionType,
  type ContentActionReasonCategory,
} from "@/entities/admin-content";

const REASON_OPTIONS: { value: ContentActionReasonCategory; label: string }[] = [
  { value: "adult", label: REASON_CATEGORY_LABELS.adult },
  { value: "copyright", label: REASON_CATEGORY_LABELS.copyright },
  { value: "hate", label: REASON_CATEGORY_LABELS.hate },
  { value: "spam", label: REASON_CATEGORY_LABELS.spam },
  { value: "other", label: REASON_CATEGORY_LABELS.other },
];

function isReasonCategory(value: string): value is ContentActionReasonCategory {
  return REASON_OPTIONS.some((option) => option.value === value);
}

const ACTION_TITLE: Record<AdminContentActionType, string> = {
  restrict: "이용제한 부과",
  delete: "삭제",
  "lift-restriction": "이용제한 해제",
  reject: "반려",
};

const ACTION_EFFECT: Record<AdminContentActionType, string> = {
  restrict: "이용제한을 부과합니다. 작품이 즉시 비공개로 전환되고 제작자에게 알림이 갑니다.",
  delete: "삭제합니다. 이 작업은 되돌릴 수 없으며 제작자에게 알림이 갑니다.",
  "lift-restriction": "이용제한을 해제합니다. 작품이 원래 공개범위로 되돌아갑니다.",
  reject: "",
};

const SUCCESS_MESSAGE: Record<AdminContentActionType, string> = {
  restrict: "이용제한을 부과했어요.",
  delete: "삭제 처리했어요.",
  "lift-restriction": "이용제한을 해제했어요.",
  reject: "",
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

type Props = {
  contentId: string;
  contentName: string;
  action: Extract<AdminContentActionType, "restrict" | "delete" | "lift-restriction">;
};

/** goal-prompt.md 2단계 T-10 — 조치 확인 다이얼로그. `restrict`/`delete`는 사유 카테고리가
 * 필수라 비어 있으면 확정 버튼이 비활성이다(API도 `reasonCategory` 누락 시 422를 낸다).
 * `lift-restriction`은 `Notification`을 만들지 않아 사유 카테고리를 고를 근거가 없다 — 대신
 * 관리자 코멘트가 필수다(비어 있으면 API가 422). 삭제는 기존 `DeleteConfirmModal`
 * (features/act-on-report)의 콘텐츠명 정확 입력 패턴을 그대로 재사용해 이 다이얼로그 안에
 * 인라인으로 뒀다 — 사유 선택까지 한 다이얼로그에서 끝내려면 별도 모달을 이어붙이는 것보다
 * 패턴만 재사용하는 쪽이 사용자에게 확인 단계가 하나로 보인다. */
export const ContentActionConfirmModal = createCallable<Props, void>(({ call, contentId, contentName, action }) => {
  const [reasonCategory, setReasonCategory] = useState<ContentActionReasonCategory>();
  const [adminComment, setAdminComment] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const actionMutation = useContentActionMutation(contentId);

  const requiresReasonCategory = action !== "lift-restriction";
  const requiresNameMatch = action === "delete";
  const canConfirm =
    (requiresReasonCategory ? Boolean(reasonCategory) : adminComment.trim().length > 0) &&
    (!requiresNameMatch || confirmText.trim() === contentName);

  const handleConfirm = async () => {
    if (!canConfirm) return;

    try {
      await actionMutation.mutateAsync({
        action,
        reasonCategory: requiresReasonCategory ? reasonCategory : undefined,
        adminComment: adminComment.trim() || undefined,
      });
      toast.success(SUCCESS_MESSAGE[action]);
      call.end();
    } catch {
      toast.error(ERROR_MESSAGE);
    }
  };

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{ACTION_TITLE[action]}</DialogTitle>
          <DialogDescription>
            <span className="font-medium text-foreground">{contentName}</span>에 대해 {ACTION_EFFECT[action]}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {requiresReasonCategory && (
            <div className="flex flex-col gap-1.5">
              <Label>사유 카테고리</Label>
              <Select
                value={reasonCategory ?? ""}
                onValueChange={(value) => setReasonCategory(isReasonCategory(value) ? value : undefined)}
              >
                <SelectTrigger className="w-full" aria-label="사유 카테고리">
                  <SelectValue placeholder="사유를 선택하세요" />
                </SelectTrigger>
                <SelectContent>
                  {REASON_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label>관리자 코멘트 {requiresReasonCategory ? "(선택)" : "(필수)"}</Label>
            <Textarea
              value={adminComment}
              onChange={(event) => setAdminComment(event.target.value)}
              placeholder={requiresReasonCategory ? "제작자에게 전달할 코멘트" : "해제 사유를 입력하세요"}
              rows={3}
            />
          </div>

          {requiresNameMatch && (
            <div className="flex flex-col gap-1.5">
              <Label>
                삭제를 확정하려면 작품명 <span className="font-medium text-foreground">{contentName}</span>을(를)
                정확히 입력하세요
              </Label>
              <Input
                value={confirmText}
                onChange={(event) => setConfirmText(event.target.value)}
                placeholder={contentName}
                autoFocus
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end()}>
            취소
          </Button>
          <Button
            type="button"
            variant={action === "delete" ? "destructive" : "default"}
            disabled={!canConfirm || actionMutation.isPending}
            onClick={() => void handleConfirm()}
          >
            {actionMutation.isPending ? "처리 중..." : "조치 확정"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
