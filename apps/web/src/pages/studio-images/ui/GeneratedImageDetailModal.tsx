import type { ApiError } from "@ai-character-chat/api-types";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { BookOpen, ChevronRight, Trash2, UserRound } from "lucide-react";
import { toast } from "sonner";

import {
  generatedImagesKeys,
  useDeleteGeneratedImageMutation,
  type GeneratedImageItem,
} from "@/entities/generated-image";
import { ConfirmChatRoomActionModal } from "@/features/manage-chat-room";

const createdAtFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const FIELD_LABEL: Record<GeneratedImageItem["usages"][number]["field"], string> = {
  thumbnail: "썸네일",
  situationalImage: "상황 이미지",
};

/** prd-image-library US-005/US-006 — 그리드 셀을 눌러 여는 생성 이미지 상세 모달. 이 이미지를 쓰는
 * 작품(usages) 목록을 보여주고 각 항목에서 해당 작품 상세로 이동하며, 미사용 이미지는 여기서
 * 삭제한다(사용 중이면 비활성 + 사유 안내). */
export function GeneratedImageDetailModal({
  image,
  onClose,
}: {
  image: GeneratedImageItem;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const deleteMutation = useDeleteGeneratedImageMutation(image.assetId);
  const isInUse = image.usages.length > 0;

  const handleDelete = () => {
    void ConfirmChatRoomActionModal.call({
      title: "이미지를 삭제할까요?",
      description: "삭제한 이미지는 복구할 수 없어요.",
      confirmLabel: "삭제",
      mutationFn: async (call) => {
        try {
          await deleteMutation.mutateAsync();
          toast.success("이미지를 삭제했어요.");
          void queryClient.invalidateQueries({ queryKey: generatedImagesKeys.list() });
          call.end();
          onClose();
        } catch (error) {
          const apiError = error as ApiError;
          if (apiError.status === 409) {
            // 조회와 삭제 사이에 다른 탭에서 작품에 붙인 경합 — 클라이언트의 usages 판단만
            // 믿지 않고 목록을 다시 받아, 확인 모달이 닫힌 뒤 갱신된 사용처가 보이게 한다.
            await queryClient.invalidateQueries({ queryKey: generatedImagesKeys.list() });
            toast.error("이미지가 방금 작품에 사용되어 삭제할 수 없어요.");
            call.end();
          } else {
            toast.error("삭제에 실패했어요. 잠시 후 다시 시도해주세요.");
          }
        }
      },
    });
  };

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      {/* 원본 비율 이미지 때문에 높이가 낮은 뷰포트에서는 모달이 화면을 넘는다 — 삭제 푸터까지
          닿도록 모달 내부 스크롤을 허용한다(바깥 페이지는 Radix가 스크롤을 잠근다). */}
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>생성 이미지</DialogTitle>
          <DialogDescription>
            <time dateTime={image.createdAt}>
              {createdAtFormatter.format(new Date(image.createdAt))}
            </time>{" "}
            생성
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-hidden rounded-lg bg-muted">
          <img src={image.imageUrl} alt="" className="aspect-square w-full object-cover" />
        </div>

        <div className="flex flex-col gap-1.5">
          <h3 className="text-sm font-medium text-foreground">사용 중인 작품</h3>
          {image.usages.length === 0 ? (
            <p className="text-sm text-muted-foreground">아직 사용 중인 작품이 없어요.</p>
          ) : (
            <ul className="flex flex-col">
              {image.usages.map((usage) => (
                <li key={`${usage.contentId}-${usage.field}`}>
                  <Link
                    to="/content/$type/$id"
                    params={{ type: usage.contentType, id: usage.contentId }}
                    className="-mx-2 flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-accent motion-safe:transition-colors focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {usage.contentType === "character" ? (
                      <UserRound aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <BookOpen aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                      {usage.contentTitle}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {FIELD_LABEL[usage.field]}
                    </span>
                    <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <DialogFooter className="sm:items-center">
          {isInUse && (
            <p className="text-xs text-muted-foreground sm:mr-auto">
              위 작품에서 사용 중이라 삭제할 수 없어요.
            </p>
          )}
          <Button type="button" variant="destructive" disabled={isInUse} onClick={handleDelete}>
            <Trash2 aria-hidden />
            이미지 삭제
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
