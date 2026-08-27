import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Lock } from "lucide-react";
import { createCallable } from "react-call";

import { useCharacterImageArchiveQuery } from "../../../entities/character-image-archive";

type Props = {
  characterId: string;
};

// techspec-chat-character.md §2, US-074/075 — "더보기 > 이미지 보관함"에서 여는 읽기 전용 react-call
// 모달(PlayGuideModal과 동일하게 mutationFn/useMutationFlow 불필요). exposed=false 항목은 서버가
// 내려준 블러 imageUrl 위에 자물쇠 아이콘만 오버레이하고 클라이언트 사이드 블러 처리는 하지 않는다.
export const ImageArchiveModal = createCallable<Props, void>(({ call, characterId }) => {
  const open = !call.ended;
  const archiveQuery = useCharacterImageArchiveQuery(characterId, open);
  const images = archiveQuery.data;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && call.end()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>이미지 보관함</DialogTitle>
          <DialogDescription>대화 중 만난 이미지를 모아봤어요.</DialogDescription>
        </DialogHeader>

        {archiveQuery.isPending ? (
          <div className="grid grid-cols-3 gap-2">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="aspect-square animate-pulse rounded-md bg-muted" />
            ))}
          </div>
        ) : archiveQuery.isError ? (
          <p className="py-4 text-center text-sm text-destructive-text">
            불러오지 못했어요. 잠시 후 다시 시도해주세요.
          </p>
        ) : images !== undefined && images.length > 0 ? (
          <div className="grid grid-cols-3 gap-2">
            {images.map((image) => (
              <div key={image.id} className="relative aspect-square overflow-hidden rounded-md bg-muted">
                {/* US-013 — 모달 안 그리드는 열리는 순간 이미 뷰포트라 lazy가 이득이 없다(decoding만). */}
                <img
                  src={image.imageUrl}
                  alt={image.exposed ? "노출된 이미지" : "아직 보지 못한 이미지"}
                  decoding="async"
                  className="h-full w-full object-cover"
                />
                {!image.exposed && (
                  <div className="absolute inset-0 flex items-center justify-center bg-foreground/40">
                    <Lock aria-hidden className="size-5 text-background" />
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-muted-foreground">등록된 이미지가 없어요.</p>
        )}
      </DialogContent>
    </Dialog>
  );
});
