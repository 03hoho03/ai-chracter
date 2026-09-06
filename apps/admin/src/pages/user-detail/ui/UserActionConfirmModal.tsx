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
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { REASON_CATEGORY_LABELS, type ContentActionReasonCategory } from "@/entities/admin-content";
import { useSuspendUserMutation, useUnsuspendUserMutation, useWarnUserMutation } from "@/entities/admin-user";

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

type UserActionType = "warn" | "suspend" | "unsuspend";

const ACTION_TITLE: Record<UserActionType, string> = {
  warn: "경고",
  suspend: "정지",
  unsuspend: "정지 해제",
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

type Props = {
  userId: string;
  action: UserActionType;
  restrictableContentCount: number;
};

/** ContentActionConfirmModal과 같은 결 — `warn`/`suspend`는 사유 카테고리가 필수라 비어 있으면
 * 확정 버튼이 비활성이다. `unsuspend`는 `Notification`을 만들지 않아 사유 카테고리를 고를 근거가
 * 없다 — 대신 관리자 코멘트가 필수다(비어 있으면 API가 422). 콘텐츠명 정확 입력 같은 강한 확인은
 * 넣지 않는다 — 정지·해제는 멱등이고 가역이다(2단계가 그 확인을 되돌릴 수 없는 삭제에만 썼다).
 * `suspend`는 실제로 이용제한으로 전환될 작품 개수(상세 응답의 `restrictableContentCount` — 이미
 * restricted/deleted인 작품은 제외한 값)를 미리 보여주고, 성공 시 응답의 `restrictedContentCount`로
 * 실제 내려간 개수를 toast에 담는다. 두 값은 항상 일치해야 정지 확인의 예고가 사실과 맞는다. */
export const UserActionConfirmModal = createCallable<Props, void>(({ call, userId, action, restrictableContentCount }) => {
  const [reasonCategory, setReasonCategory] = useState<ContentActionReasonCategory>();
  const [adminComment, setAdminComment] = useState("");

  const warnMutation = useWarnUserMutation(userId);
  const suspendMutation = useSuspendUserMutation(userId);
  const unsuspendMutation = useUnsuspendUserMutation(userId);

  const requiresReasonCategory = action !== "unsuspend";
  const canConfirm = requiresReasonCategory ? Boolean(reasonCategory) : adminComment.trim().length > 0;
  const isPendingByAction: Record<UserActionType, boolean> = {
    warn: warnMutation.isPending,
    suspend: suspendMutation.isPending,
    unsuspend: unsuspendMutation.isPending,
  };
  const isPending = isPendingByAction[action];

  const handleConfirm = async () => {
    if (!canConfirm) return;

    try {
      if (action === "warn") {
        if (!reasonCategory) return;
        await warnMutation.mutateAsync({ reasonCategory, adminComment: adminComment.trim() || undefined });
        toast.success("경고를 부과했어요.");
      } else if (action === "suspend") {
        if (!reasonCategory) return;
        const result = await suspendMutation.mutateAsync({
          reasonCategory,
          adminComment: adminComment.trim() || undefined,
        });
        toast.success(`정지했어요. 작품 ${result.restrictedContentCount}건이 이용제한으로 전환됐어요.`);
      } else {
        await unsuspendMutation.mutateAsync({ adminComment: adminComment.trim() });
        toast.success("정지를 해제했어요.");
      }
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
            {action === "warn" && "이 유저에게 경고를 부과합니다."}
            {action === "suspend" &&
              (restrictableContentCount > 0
                ? `이 유저를 정지합니다. 작품 ${restrictableContentCount}건이 함께 이용제한으로 전환됩니다.`
                : "이 유저를 정지합니다.")}
            {action === "unsuspend" && "이 유저의 정지를 해제합니다. 작품은 이용제한 상태로 남습니다."}
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
              placeholder={requiresReasonCategory ? "유저에게 전달할 코멘트" : "해제 사유를 입력하세요"}
              rows={3}
            />
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end()}>
            취소
          </Button>
          <Button type="button" disabled={!canConfirm || isPending} onClick={() => void handleConfirm()}>
            {isPending ? "처리 중..." : "조치 확정"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
