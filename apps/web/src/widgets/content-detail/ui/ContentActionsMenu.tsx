import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { EyeOff, Flag, MoreHorizontal, Share2 } from "lucide-react";
import { toast } from "sonner";

import { useReportContentMutation, type ContentVisibility } from "../../../entities/content";
import { MakeContentPrivateModal } from "../../../features/make-content-private";
import { ReportContentModal } from "../../../features/report-content";

/** techspec-content-detail.md §5, US-018/US-048/US-115 — 공유(클립보드 복사)/신고/(본인 소유일 때)
 * 비공개 전환 진입점인 "⋯" 메뉴. */
export function ContentActionsMenu({
  contentId,
  creatorUserId,
  isOwner,
  visibility,
}: {
  contentId: string;
  creatorUserId: string;
  isOwner: boolean;
  visibility: ContentVisibility;
}) {
  const reportMutation = useReportContentMutation(contentId);
  // US-115(FR-67) — 완전 삭제 액션은 없고 비공개 전환만 허용되며, 이미 비공개인 항목엔 노출하지 않는다.
  const canMakePrivate = isOwner && visibility !== "private";

  const handleShare = async () => {
    await navigator.clipboard.writeText(window.location.href);
    toast.success("링크가 복사되었어요.");
  };

  const handleReport = () => {
    void ReportContentModal.call({
      mutationFn: async (call, reasonCategory) => {
        try {
          await reportMutation.mutateAsync(reasonCategory);
          toast.success("신고가 접수되었어요.");
          call.end();
        } catch (error) {
          const apiError = error as ApiError;
          toast.error(
            apiError.status === 401
              ? "로그인 후 신고할 수 있어요."
              : "신고 접수에 실패했어요. 잠시 후 다시 시도해주세요.",
          );
        }
      },
    });
  };

  const handleMakePrivate = () => {
    void MakeContentPrivateModal.call({ contentId, creatorUserId });
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label="더보기">
          <MoreHorizontal aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => void handleShare()}>
          <Share2 aria-hidden />
          공유
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleReport}>
          <Flag aria-hidden />
          신고
        </DropdownMenuItem>
        {canMakePrivate && (
          <DropdownMenuItem onSelect={handleMakePrivate}>
            <EyeOff aria-hidden />
            비공개 전환
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
