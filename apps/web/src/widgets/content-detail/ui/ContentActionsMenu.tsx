import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Flag, MoreHorizontal, Share2 } from "lucide-react";
import { toast } from "sonner";

import {
  useReportContentMutation,
  type ContentVisibility,
  type ModerationStatus,
} from "@/entities/content";
import { VisibilityTransitionMenuItems } from "@/features/change-content-visibility";
import { ReportContentModal } from "@/features/report-content";
import { isApiError } from "@/shared/lib/api/client";

type ContentActionsMenuProps = {
  contentId: string;
  creatorUserId: string;
  isOwner: boolean;
  /** 현재 공개범위 — 전환 메뉴에서 이 값과 같은 항목을 빼는 데 쓴다. */
  visibility: ContentVisibility;
  /** 이용제한이면 전환 항목이 비활성이 된다(US-008). 이 화면에는 실제로 `normal`만 오지만
   * (`ContentDetailView`가 `canViewDetailPage`로 restricted/deleted를 이미 걷어낸다) 값을 받아 넘긴다 —
   * 호출부가 그 근거를 눈에 보이게 적게 하려는 것이다. */
  moderationStatus: ModerationStatus;
};

/** techspec-content-detail.md §5, US-018/US-048/US-115 — 공유(클립보드 복사)/신고/(본인 소유일 때)
 * 공개범위 전환 진입점인 "⋯" 메뉴. */
export function ContentActionsMenu({
  contentId,
  creatorUserId,
  isOwner,
  visibility,
  moderationStatus,
}: ContentActionsMenuProps) {
  const reportMutation = useReportContentMutation(contentId);

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
          const apiError = isApiError(error) ? error : null;
          toast.error(
            apiError?.status === 401
              ? "로그인 후 신고할 수 있어요."
              : "신고 접수에 실패했어요. 잠시 후 다시 시도해주세요.",
          );
        }
      },
    });
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label="더보기">
          <MoreHorizontal aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      {/* 메뉴 폭은 프리미티브가 트리거 폭에 고정한다(`w-(--radix-dropdown-menu-trigger-width)`).
          아이콘 트리거라 128px(min-w-32)에 갇혀 "링크공개로 전환"이 두 줄로 깨지므로 내용에 맞춘다. */}
      <DropdownMenuContent align="end" className="w-auto">
        <DropdownMenuItem onSelect={() => void handleShare()}>
          <Share2 aria-hidden />
          공유
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleReport}>
          <Flag aria-hidden />
          신고
        </DropdownMenuItem>

        {/* US-005 — 완전 삭제는 여전히 없고(US-115/FR-67) 공개범위 전환만 허용된다. */}
        {isOwner && (
          <>
            <DropdownMenuSeparator />
            <VisibilityTransitionMenuItems
              contentId={contentId}
              creatorUserId={creatorUserId}
              currentVisibility={visibility}
              moderationStatus={moderationStatus}
            />
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
