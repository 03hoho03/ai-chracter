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
import { isApiError } from "@/shared/api/client";

type ContentActionsMenuProps = {
  contentId: string;
  creatorUserId: string;
  isOwner: boolean;
  /** 현재 공개범위 — 전환 메뉴에서 이 값과 같은 항목을 빼는 데 쓴다. */
  visibility: ContentVisibility;
  /** 이용제한이면 전환 항목이 비활성이 된다. 이 화면에는 실제로 `normal`만 오지만
   * (`ContentDetailView`가 `canViewDetailPage`로 restricted/deleted를 이미 걷어낸다) 값을 받아 넘긴다 —
   * 호출부가 그 근거를 눈에 보이게 적게 하려는 것이다. */
  moderationStatus: ModerationStatus;
  /** 모달 헤더에서는 옆의 닫기 X(32px)와 같은 크기로 맞춘다. 풀페이지는 기본 크기 그대로다. */
  triggerSize?: "icon" | "icon-sm";
};

/** 공유(클립보드 복사)와, 남의 작품이면 신고 / 본인 소유면
 * 공개범위 전환 진입점인 "⋯" 메뉴. */
export function ContentActionsMenu({
  contentId,
  creatorUserId,
  isOwner,
  visibility,
  moderationStatus,
  triggerSize = "icon",
}: ContentActionsMenuProps) {
  const reportMutation = useReportContentMutation(contentId);

  const handleShare = async () => {
    // 권한 거부·비보안 컨텍스트에서는 쓰기가 거부된다 — 삼키면 눌러도 아무 반응이 없다.
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast.success("링크가 복사되었어요.");
    } catch {
      toast.error("링크를 복사하지 못했어요. 주소창의 링크를 직접 복사해주세요.");
    }
  };

  const handleReport = () => {
    void ReportContentModal.call({
      mutationFn: async (call, reasonCategory) => {
        try {
          await reportMutation.mutateAsync(reasonCategory);
          toast.success("신고가 접수되었어요.");
          call.end();
        } catch (error) {
          const apiError = isApiError(error) ? error : undefined;
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
      {/* ghost 기본 hover(`bg-muted`)는 모달 표면(`popover`)과 같은 값이라 사라진다. `secondary`는 모달과
          풀페이지 배경 양쪽에서 보인다(닫기 X와 같은 처방). */}
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size={triggerSize}
          aria-label="더보기"
          className="hover:bg-secondary aria-expanded:bg-secondary"
        >
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
        {/* 자기 작품은 신고할 수 없다 — 서버도 403으로 거부하므로 보여 주면 누르는 순간 실패한다. */}
        {!isOwner && (
          <DropdownMenuItem onSelect={handleReport}>
            <Flag aria-hidden />
            신고
          </DropdownMenuItem>
        )}

        {/* 완전 삭제는 여전히 없고 공개범위 전환만 허용된다. */}
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
