import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Link } from "@tanstack/react-router";
import { BookOpen, Flag, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";

import { toWebnovelReportErrorMessage, useReportWebnovelMutation } from "@/entities/webnovel";
import { ReportContentModal } from "@/features/report-content";

/** 작품 정보의 "⋯" — 남의 노벨이면 신고, 내가 공개한 노벨이면 내 소설의 작품 정보(공개 설정이 있는 곳)로 가는 길. */
export function WebnovelActionsMenu({ novelId, isPublisher }: { novelId: string; isPublisher: boolean }) {
  const report = useReportWebnovelMutation(novelId);

  function handleReport() {
    void ReportContentModal.call({
      title: "노벨 신고하기",
      mutationFn: async (call, reasonCategory) => {
        try {
          await report.mutateAsync({ reasonCategory });
          toast.success("신고가 접수되었어요.");
          call.end();
        } catch (error) {
          toast.error(toWebnovelReportErrorMessage(error));
        }
      },
    });
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label="더보기" className="hover:bg-secondary aria-expanded:bg-secondary">
          <MoreHorizontal aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-auto">
        {isPublisher ? (
          <DropdownMenuItem asChild>
            <Link to="/novels/$novelId" params={{ novelId }}>
              <BookOpen aria-hidden />
              내 소설에서 관리
            </Link>
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onSelect={handleReport}>
            <Flag aria-hidden />
            신고하기
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
