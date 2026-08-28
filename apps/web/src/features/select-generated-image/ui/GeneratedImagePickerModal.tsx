import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { ExternalLink, Images } from "lucide-react";
import { createCallable } from "react-call";

import { useGeneratedImagesQuery } from "@/entities/generated-image";

export type PickedGeneratedImage = { assetId: string; imageUrl: string };

// techspec-builder-story.md §2 — 캐릭터/스토리 빌더가 공유하는 "생성한 이미지에서 선택" 피커.
// PlayGuideModal(US-068)과 동일하게 useMutationFlow 없는 순수 조회+선택 모달이다: 그리드 셀 클릭이
// 곧 결과 확정이라 별도 제출 단계가 없다. "새로 생성하기"는 새 탭을 열 뿐 이 모달/호출한 폼의 상태에는
// 전혀 영향을 주지 않는다(평범한 <a target="_blank">).
export const GeneratedImagePickerModal = createCallable<void, PickedGeneratedImage | null>(
  ({ call }) => {
    const open = !call.ended;
    const galleryQuery = useGeneratedImagesQuery(open);

    return (
      <Dialog open={open} onOpenChange={(next) => !next && call.end(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>생성한 이미지에서 선택</DialogTitle>
            <DialogDescription>이전에 생성해 둔 이미지 중 하나를 골라 등록해요.</DialogDescription>
          </DialogHeader>

          <Button variant="ghost" size="sm" className="w-fit" asChild>
            <a href="/studio/images" target="_blank" rel="noopener noreferrer">
              새로 생성하기
              <ExternalLink aria-hidden />
            </a>
          </Button>

          <GeneratedImageGridBody query={galleryQuery} onPick={call.end} />
        </DialogContent>
      </Dialog>
    );
  },
);

/** 네 상태(로딩·에러·그리드·빈 목록)가 배타적이라 early return으로 순서를 강제한다(COMP-04). */
function GeneratedImageGridBody({
  query,
  onPick,
}: {
  query: ReturnType<typeof useGeneratedImagesQuery>;
  onPick: (picked: { assetId: string; imageUrl: string }) => void;
}) {
  if (query.isPending) {
    return (
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="aspect-square animate-pulse rounded-md bg-muted" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <p className="py-4 text-center text-sm text-destructive-text">
        불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const images = query.data;
  if (images === undefined || images.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-6 text-center">
        <Images aria-hidden className="size-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          아직 생성한 이미지가 없어요.
          <br />
          새로 생성하고 다시 열어보면 여기에 나타나요.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-3 gap-2">
      {images.map((image) => (
        <button
          key={image.assetId}
          type="button"
          onClick={() => onPick({ assetId: image.assetId, imageUrl: image.imageUrl })}
          className="aspect-square overflow-hidden rounded-md bg-muted transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {/* US-013 — 모달 안 그리드는 열리는 순간 이미 뷰포트라 lazy가 이득이 없다(decoding만). */}
          <img src={image.imageUrl} alt="" decoding="async" className="size-full object-cover" />
        </button>
      ))}
    </div>
  );
}
