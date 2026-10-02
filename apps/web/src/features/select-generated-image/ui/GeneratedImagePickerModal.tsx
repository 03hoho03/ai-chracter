import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { ExternalLink, Images } from "lucide-react";

import { useGeneratedImagesQuery } from "@/entities/generated-image";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { generatedImageAccessibleName } from "../model/generatedImageAccessibleName";

export type PickedGeneratedImage = { assetId: string; imageUrl: string };

/** 호출부마다 달라지는 문구와 "새로 생성하기" 링크. 전부 생략하면 빌더 문구·링크가 나온다 —
 * 이 피커는 빌더용으로 먼저 생겼고, 생성 화면 안에서 열 때는 "등록"도 새 탭 생성 링크도 맞지 않는다
 * (이미 생성 화면이다). */
export type GeneratedImagePickerOptions = {
  title?: string;
  description?: string;
  emptyHint?: string;
  shouldShowCreateLink?: boolean;
  /** 채우려는 자리에 지금 들어 있는 이미지. 그 버튼에 표식을 얹고 `aria-current` 를 준다. */
  currentAssetId?: string;
  /** 다른 자리에서 이미 쓰는 이미지 → 그 자리를 말하는 한 구절. 표식은 짧게 "사용 중"이고 구절은 접근 이름이 싣는다. */
  usedAssetLabels?: ReadonlyMap<string, string>;
};

// 접근 이름에 넣는 만든 때. 같은 날 여러 번 만들기 때문에 날짜와 분까지 읽는다.
const CREATED_AT_FORMAT = new Intl.DateTimeFormat("ko-KR", {
  month: "long",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

// 캐릭터/스토리 빌더와 이미지 생성 화면(참조 이미지)이 공유하는 "생성한 이미지에서 선택" 피커.
// PlayGuideModal과 동일하게 useMutationFlow 없는 순수 조회+선택 모달이다: 그리드 셀 클릭이
// 곧 결과 확정이라 별도 제출 단계가 없다. "새로 생성하기"는 새 탭을 열 뿐 이 모달/호출한 폼의 상태에는
// 전혀 영향을 주지 않는다(평범한 <a target="_blank">).
export const GeneratedImagePickerModal = createCallable<GeneratedImagePickerOptions, PickedGeneratedImage | undefined>(
  ({
    call,
    title = "생성한 이미지에서 선택",
    description = "이전에 생성해 둔 이미지 중 하나를 골라 등록해요.",
    emptyHint = "새로 생성하고 다시 열어보면 여기에 나타나요.",
    shouldShowCreateLink = true,
    currentAssetId,
    usedAssetLabels,
  }) => {
    const isOpen = !call.ended;
    const galleryQuery = useGeneratedImagesQuery(isOpen);

    return (
      <Dialog open={isOpen} onOpenChange={(next) => !next && call.end(undefined)}>
        {/* 이미지가 많으면 그리드가 화면보다 길어진다 — `DialogContent`엔 최대 높이도 내부 스크롤도
            없어서, 빼먹으면 Radix가 body 스크롤을 잠근 채 아래 행과 닫기에 닿을 방법이 없다. */}
        <DialogContent className="max-h-dialog overflow-y-auto sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="break-keep">{description}</DialogDescription>
          </DialogHeader>

          {shouldShowCreateLink && (
            <Button variant="ghost" size="sm" className="w-fit hover:bg-secondary" asChild>
              <a href="/studio/images" target="_blank" rel="noopener noreferrer">
                새로 생성하기
                <ExternalLink aria-hidden />
              </a>
            </Button>
          )}

          <GeneratedImageGridBody
            query={galleryQuery}
            emptyHint={emptyHint}
            currentAssetId={currentAssetId}
            usedAssetLabels={usedAssetLabels}
            onPick={call.end}
          />
        </DialogContent>
      </Dialog>
    );
  },
);

type GeneratedImageGridBodyProps = {
  query: ReturnType<typeof useGeneratedImagesQuery>;
  emptyHint: string;
  currentAssetId: string | undefined;
  usedAssetLabels: ReadonlyMap<string, string> | undefined;
  onPick: (picked: { assetId: string; imageUrl: string }) => void;
};

/** 네 상태(로딩·에러·그리드·빈 목록)가 배타적이라 early return으로 순서를 강제한다. */
function GeneratedImageGridBody({
  query,
  emptyHint,
  currentAssetId,
  usedAssetLabels,
  onPick,
}: GeneratedImageGridBodyProps) {
  if (query.isPending) {
    return (
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="aspect-square animate-pulse rounded-md bg-secondary" />
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
          {emptyHint}
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-3 gap-2">
      {images.map((image, index) => {
        const isCurrent = image.assetId === currentAssetId;
        const usedLabel = usedAssetLabels?.get(image.assetId);
        const marker = toMarker(isCurrent, usedLabel);
        return (
          <button
            key={image.assetId}
            type="button"
            aria-label={generatedImageAccessibleName({
              position: index + 1,
              createdAtLabel: CREATED_AT_FORMAT.format(new Date(image.createdAt)),
              isCurrent,
              usedLabel,
            })}
            aria-current={isCurrent ? "true" : undefined}
            onClick={() => onPick({ assetId: image.assetId, imageUrl: image.imageUrl })}
            className="relative aspect-square overflow-hidden rounded-md bg-secondary motion-safe:transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {/* 모달 안 그리드는 열리는 순간 이미 뷰포트라 lazy가 이득이 없다(decoding만). */}
            <img src={image.imageUrl} alt="" decoding="async" className="size-full object-cover" />
            {marker && (
              // 이미지 위에 얹는 글자라 테마와 무관한 스크림 쌍을 쓴다. 이름은 버튼의 접근 이름이 이미 싣는다.
              <span
                aria-hidden
                className="pointer-events-none absolute top-1 left-1 rounded-full bg-scrim/70 px-1.5 py-0.5 text-badge font-medium text-scrim-foreground"
              >
                {marker}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** 이미지 위 표식 글자. 둘 다면 지금 이미지 쪽이 고르는 판단에 더 가깝다(다른 칸의 쓰임은 접근 이름이 함께 싣는다). */
function toMarker(isCurrent: boolean, usedLabel: string | undefined): string | undefined {
  if (isCurrent) return "지금 이미지";
  if (usedLabel) return "사용 중";
  return undefined;
}
