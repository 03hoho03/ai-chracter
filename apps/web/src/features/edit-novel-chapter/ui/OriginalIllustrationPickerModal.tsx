import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Images } from "lucide-react";

import { createCallable } from "@/shared/lib/callable/createCallable";

import {
  useNovelIllustrationCandidatesQuery,
  type NovelIllustrationCandidate,
} from "../api/useNovelIllustrationCandidatesQuery";

type OriginalIllustrationPickerModalProps = {
  novelId: string;
  /** 바꾸려는 자리에 지금 들어 있는 그림. 그 칸에 표식을 얹고 `aria-current` 를 준다. */
  currentAssetId?: string;
};

export type PickedOriginalIllustration = { assetId: string };

const KIND_LABEL: Record<NovelIllustrationCandidate["kind"], string> = {
  thumbnail: "대표 이미지",
  situationalImage: "상황 이미지",
  mediaBook: "미디어 북 이미지",
};

/** 원작 그림에서 삽화 고르기. 칸을 누르는 순간 고른 것이라 제출 단계가 없다(내 이미지 고르기 창과 같은 꼴). 고른 그림은 독자
 * 화면에서 "원작 이미지" 캡션과 함께 선다. */
export const OriginalIllustrationPickerModal = createCallable<
  OriginalIllustrationPickerModalProps,
  PickedOriginalIllustration | undefined
>(({ call, novelId, currentAssetId }) => {
  const isOpen = !call.ended;
  const query = useNovelIllustrationCandidatesQuery(novelId, isOpen);

  return (
    <Dialog open={isOpen} onOpenChange={(next) => !next && call.end(undefined)}>
      {/* 후보가 많으면 격자가 화면보다 길어진다 — 격자만 `DialogBody` 에서 스크롤하고 제목·닫기는 위에 남긴다. */}
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>원작 이미지에서 고르기</DialogTitle>
          <DialogDescription className="break-keep">
            원작에서 본 그림을 삽화로 넣어요. 독자에게는 그림 아래 &lsquo;원작 이미지&rsquo;가 함께 보여요.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <OriginalIllustrationPickerBody
            isPending={query.isPending}
            isError={query.isError}
            items={query.data ?? []}
            currentAssetId={currentAssetId}
            onPick={(assetId) => call.end({ assetId })}
          />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
});

type OriginalIllustrationPickerBodyProps = {
  isPending: boolean;
  isError: boolean;
  items: readonly NovelIllustrationCandidate[];
  currentAssetId: string | undefined;
  onPick: (assetId: string) => void;
};

/** 네 상태(불러오는 중·실패·빈 목록·격자)가 배타적이라 차례로 돌려준다. 칸은 모달(`popover` 표면) 위라 웰이 `secondary` 다 —
 * `muted` 는 이 표면과 같은 값이라 사라진다. 고르는 기준이 그림 전체라 자르지 않고 `object-contain` 이다. */
export function OriginalIllustrationPickerBody({
  isPending,
  isError,
  items,
  currentAssetId,
  onPick,
}: OriginalIllustrationPickerBodyProps) {
  if (isPending) {
    return (
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2, 3, 4, 5].map((index) => (
          <div key={index} className="aspect-square animate-pulse rounded-lg bg-secondary" />
        ))}
      </div>
    );
  }

  if (isError) {
    return <p className="py-4 text-center text-sm text-destructive-text">불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-6 text-center">
        <Images aria-hidden className="size-8 text-muted-foreground" />
        <p className="text-sm break-keep text-muted-foreground">
          원작 방에서 본 그림이 여기 나와요.
          <br />
          아직 본 그림이 없어요.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-3 gap-2">
      {items.map((item, index) => {
        const isCurrent = item.assetId === currentAssetId;
        return (
          <button
            key={item.assetId}
            type="button"
            aria-label={`${KIND_LABEL[item.kind]} ${index + 1}`}
            aria-current={isCurrent ? "true" : undefined}
            onClick={() => onPick(item.assetId)}
            className="relative flex aspect-square items-center justify-center overflow-hidden rounded-lg bg-secondary motion-safe:transition-opacity hover:opacity-80 focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {/* 모달 안 격자는 열리는 순간 이미 화면 안이라 늦게 받기가 이득이 없다. */}
            <img src={item.url} alt="" decoding="async" className="size-full object-contain" />
            {isCurrent && (
              // 그림 위에 얹는 글자라 테마와 무관한 스크림 쌍을 쓴다. 이름은 버튼의 `aria-current` 가 싣는다.
              <span
                aria-hidden
                className="pointer-events-none absolute top-1 left-1 rounded-full bg-scrim/70 px-1.5 py-0.5 text-badge font-medium text-scrim-foreground"
              >
                지금 이미지
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
