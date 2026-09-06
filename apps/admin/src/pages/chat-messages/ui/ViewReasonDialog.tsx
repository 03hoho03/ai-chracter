import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { toast } from "sonner";

import { CHAT_VIEW_REASON_CATEGORY_LABELS, type ChatViewReasonCategory } from "@/entities/admin-user";
import { isApiError } from "@/shared/lib/api/client";
import { useViewChatMutation, type AdminChatMessagesResponse } from "../api/useViewChatMutation";

const REASON_OPTIONS: { value: ChatViewReasonCategory; label: string }[] = [
  { value: "report-investigation", label: CHAT_VIEW_REASON_CATEGORY_LABELS["report-investigation"] },
  { value: "appeal-review", label: CHAT_VIEW_REASON_CATEGORY_LABELS["appeal-review"] },
  { value: "legal-request", label: CHAT_VIEW_REASON_CATEGORY_LABELS["legal-request"] },
  { value: "other", label: CHAT_VIEW_REASON_CATEGORY_LABELS.other },
];

function isReasonCategory(value: string): value is ChatViewReasonCategory {
  return REASON_OPTIONS.some((option) => option.value === value);
}

type Props = {
  roomId: string;
  onCancel: () => void;
  onConfirmed: (data: AdminChatMessagesResponse) => void;
};

/** 이 화면의 진입 게이트 다이얼로그 — `__root.tsx`에 콜러블로 마운트하지 않고 페이지 안에
 * 직접 둔다(techspec §5-6). 사유를 라우터 state나 전역 콜러블로 넘기면 새로고침 시 사라져
 * 빈 화면이 되지만, 이 컴포넌트는 `ChatMessagesPage`가 `viewResult`를 아직 못 받은 동안 항상
 * 그 자리에서 다시 렌더되므로 새로고침해도 다이얼로그가 다시 뜬다. */
export function ViewReasonDialog({ roomId, onCancel, onConfirmed }: Props) {
  const [reasonCategory, setReasonCategory] = useState<ChatViewReasonCategory>();
  const [reasonText, setReasonText] = useState("");

  const viewMutation = useViewChatMutation(roomId);

  const trimmedReasonText = reasonText.trim();
  const canConfirm = Boolean(reasonCategory) && trimmedReasonText.length > 0;

  const handleConfirm = async () => {
    if (!canConfirm || !reasonCategory) return;

    try {
      const data = await viewMutation.mutateAsync({ reasonCategory, reasonText: trimmedReasonText });
      onConfirmed(data);
    } catch (error) {
      if (isApiError(error) && error.status === 404) {
        toast.error("존재하지 않는 채팅방이에요.");
        onCancel();
        return;
      }
      toast.error("열람 처리에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>채팅 열람 사유</DialogTitle>
          <DialogDescription className="break-keep">
            이 대화를 보려면 사유가 필요해요. 열람 기록이 남습니다.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
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

          <div className="flex flex-col gap-1.5">
            <Label>사유 상세 (필수)</Label>
            <Textarea
              value={reasonText}
              onChange={(event) => setReasonText(event.target.value)}
              placeholder="열람이 필요한 이유를 입력하세요"
              rows={3}
            />
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            취소
          </Button>
          <Button type="button" disabled={!canConfirm || viewMutation.isPending} onClick={() => void handleConfirm()}>
            {viewMutation.isPending ? "처리 중..." : "확인"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
