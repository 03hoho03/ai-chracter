import { useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Images } from "lucide-react";

import { useGeneratedImagesQuery } from "@/entities/generated-image";
import { useGenerateImagesSubmit } from "@/features/generate-images";

import { GeneratedImageDetailModal } from "./GeneratedImageDetailModal";

type GeneratedImageLibraryPanelProps = {
  onNavigateToGenerate?: () => void;
  gridColumnsClassName?: string;
  // 브라우저 실측 피드백 — 좌열(98px 셀)에서는 날짜 캡션이 3행이면 72px을 먹는다. 시트는
  // 폭이 넓어 이 문제가 없으므로 기본값 true를 유지하고 레일(wide) 호출부만 false를 넘긴다
  // (ImageStudioLibraryRail.tsx). aria-label의 날짜는 이 prop과 무관하게 항상 남는다.
  isCreatedAtVisible?: boolean;
  /** 상세 모달에서 삭제가 성공한 이미지. 셸이 결과 영역에서도 그 이미지를 뺀다. */
  onImageDeleted: (assetId: string) => void;
  /** 넘기면 "참조로 쓰기" 뒤 참조 필드로 포커스를 옮기는 일을 호출부가 맡는다. 보관함 시트는 이걸로
   * 시트를 먼저 닫는다 — 시트가 열린 채로는 포커스가 시트 안에 갇혀 참조 필드에 못 간다. 넘기지
   * 않으면(좌열) 패널이 바로 참조 필드로 옮긴다. */
  onUsedAsReference?: () => void;
};

// 상세 모달이 왜 닫혔는지. 닫힌 뒤 포커스를 둘 곳이 이유마다 다르고, 모달은 닫힐 때 그 이유를
// 모르므로 닫기 직전에 여기 적어 두고 닫힘 처리에서 읽은 뒤 지운다.
type DetailCloseReason =
  | { kind: "dismiss" }
  | { kind: "reference" }
  // 지운 타일은 사라지므로 지우기 직전 목록에서 다음·이전 타일을 미리 골라 둔다.
  | { kind: "deleted"; neighborAssetIds: string[] };

// 좌열(p-4 → 208px 콘텐츠)에서는 grid-cols-2 고정이라야
// 98×98 정사각 타일이 나온다(크랙 108). sm:/md: 이스케일은 뷰포트 폭 기준이라 lg 이상(=isWide)에서
// 이 208px 고정 열에도 그대로 걸려 4열까지 욱여넣는다 — 옛 '내 이미지' 탭(뷰포트 폭에 맞춰 늘어나는
// 전체 페이지 그리드)에서 물려받은 값이라, 폭이 뷰포트가 아니라 레일에 고정되는 지금은 호출부가
// 오버라이드해야 한다. 바텀시트(폭이 뷰포트를 그대로 따라간다)는 기본값을 그대로 쓴다.
const DEFAULT_GRID_COLUMNS_CLASSNAME = "grid-cols-2 sm:grid-cols-3 md:grid-cols-4";

const CREATED_AT_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** 보관함(좌열/바텀시트). 생성 이미지를 최신순 그리드로
 * 보여준다(정렬은 서버의 created_at desc 그대로). 사용 중인 이미지에는 사용처 배지를 달고,
 * 셀을 누르면 사용처 목록·삭제·참조로 쓰기가 있는 상세 모달을 연다. 참조로 쓰기 때문에 생성 폼
 * 컨텍스트를 읽으므로 `GenerateImagesFormProvider` 안에서만 그린다.
 *
 * '내 이미지'는 더 이상 탭이 아니라서 전환할 "생성 탭"이
 * 없다(중앙 열이 이미 항상 그 화면이다). `onNavigateToGenerate`는 좁은 화면(바텀시트)에서만 의미가
 * 있어 optional로 바꿨다 — 시트를 닫으면 뒤에 있던 생성 화면이 그대로 드러난다. 넓은 화면(좌열)은
 * 생성 화면과 나란히 상시 보이므로 이 버튼을 렌더하지 않는다(호출부가 prop을 생략).
 *
 * 표면이 둘이다 — 넓은 화면 좌열은 `background`, 좁은 화면은 `SheetContent`(`popover`). 그래서 셀·
 * 스켈레톤은 두 표면 모두에서 보이는 `secondary`이고(`muted`는 시트 안에서 1.0000:1로 사라진다),
 * 사용처 배지는 채움 없는 윤곽이다(DESIGN.md Status badges — 중립 상태는 윤곽). 이 파일에는 표면
 * 표식이 없어 `mutedOnSurfaceContract` 가드가 못 잡는 자리다. 할 일: 파일 단위 휴리스틱의 이런
 * 사각지대가 재발하면 컴포넌트 트리 기반 검사를 검토한다. */
export function GeneratedImageLibraryPanel({
  onNavigateToGenerate,
  gridColumnsClassName = DEFAULT_GRID_COLUMNS_CLASSNAME,
  isCreatedAtVisible = true,
  onImageDeleted,
  onUsedAsReference,
}: GeneratedImageLibraryPanelProps) {
  const { isReferenceEnabled, unavailableReason, setReference, focusReferenceField } = useGenerateImagesSubmit();
  // 모델 목록을 못 불러온 화면에서도 보관함은 열리지만, 그때는 참조 필드가 없어 넣을 자리가 없다.
  const canUseAsReference = isReferenceEnabled && unavailableReason === undefined;
  const closeReasonRef = useRef<DetailCloseReason>({ kind: "dismiss" });
  const navigateButtonRef = useRef<HTMLButtonElement>(null);
  const galleryQuery = useGeneratedImagesQuery(true);
  const images = galleryQuery.data;
  // 항목 스냅샷이 아니라 id로 선택하고 목록에서 매번 찾는다 — 삭제 409로 목록을 다시 받으면
  // 열려 있는 상세 모달이 갱신된 usages를 보여줘야 한다(항목이 사라지면 모달도 내려간다).
  const [selectedAssetId, setSelectedAssetId] = useState<string>();
  const selectedImage = images?.find((image) => image.assetId === selectedAssetId);

  function handleImageDeleted(assetId: string) {
    const list = images ?? [];
    const index = list.findIndex((image) => image.assetId === assetId);
    const neighborAssetIds =
      index < 0
        ? []
        : [list[index + 1]?.assetId, list[index - 1]?.assetId].filter((id): id is string => id !== undefined);
    closeReasonRef.current = { kind: "deleted", neighborAssetIds };
    onImageDeleted(assetId);
  }

  // 모달은 트리거 없이 열려 스스로는 돌아갈 곳이 없다(닫히면 `<body>`). 일반 닫기는 연 타일로,
  // 삭제는 남은 이웃 타일로 보내고, 타일이 하나도 안 남으면 늘 있는 자리로 물러난다 — 시트의 빈 상태
  // 버튼, 그다음 프롬프트 입력칸, 그것도 없으면(모델 목록을 못 불러와 중앙이 대체 화면이면) 생성 탭.
  function restoreFocusAfterDetail(openedAssetId: string) {
    const reason = closeReasonRef.current;
    closeReasonRef.current = { kind: "dismiss" };

    if (reason.kind === "reference") {
      if (onUsedAsReference) onUsedAsReference();
      else focusReferenceField();
      return;
    }

    const tileAssetIds = reason.kind === "deleted" ? reason.neighborAssetIds : [openedAssetId];
    const tile = tileAssetIds
      .map((id) => document.querySelector<HTMLElement>(`[data-generated-image-tile="${id}"]`))
      .find((element) => element !== null);
    const target =
      tile ??
      navigateButtonRef.current ??
      // 프롬프트 입력칸은 다른 슬라이스의 요소라 ref가 닿지 않아 그 필드가 단 id로 찾는다.
      document.getElementById("generate-images-prompt") ??
      document.querySelector<HTMLElement>('[data-image-studio-trigger="generate-tab"]');
    target?.focus();
  }

  if (galleryQuery.isPending) {
    return <LibraryGridSkeleton gridColumnsClassName={gridColumnsClassName} />;
  }

  if (galleryQuery.isError) {
    return (
      <div className="flex flex-col items-start gap-3 py-4">
        <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
        <Button variant="outline" size="sm" onClick={() => void galleryQuery.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  if (images === undefined || images.length === 0) {
    return (
      // apps/web/CLAUDE.md — dashed 빈 상태 패널 셸은 손으로 복사된 사본이 셋(ContentListEmptyState·
      // MyWorksFullErrorState·이 파일)이다. 여기 px-4 py-10은 나머지 둘의 px-6 py-16과 다른데,
      // 레일(207px 콘텐츠 폭)에 맞춘 값이라 의도적으로 다르다 — 넓은 본문에 있는 나머지 둘은
      // 이 문제가 없어 건드리지 않았다.
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border px-4 py-10 text-center">
        <Images aria-hidden className="size-8 text-muted-foreground" />
        <p className="break-keep text-sm text-muted-foreground">
          아직 생성한 이미지가 없어요.
          <br />
          프롬프트 한 줄로 첫 이미지를 만들어보세요.
        </p>
        {onNavigateToGenerate && (
          <Button ref={navigateButtonRef} variant="outline" size="sm" onClick={onNavigateToGenerate}>
            이미지 생성하러 가기
          </Button>
        )}
      </div>
    );
  }

  return (
    <>
      <div className={cn("grid gap-3", gridColumnsClassName)}>
        {images.map((image) => {
          const createdAtLabel = CREATED_AT_FORMATTER.format(new Date(image.createdAt));
          const hasUsageBadge = image.usages.length > 0;
          return (
            <figure key={image.assetId} className="flex flex-col gap-1.5">
              <button
                type="button"
                data-generated-image-tile={image.assetId}
                // 날짜를 시각적으로 숨겨도 접근 이름에는 남긴다 — isCreatedAtVisible은 <figcaption>의
                // 렌더 여부만 바꾼다.
                aria-label={`${createdAtLabel} 생성 이미지 상세 보기`}
                onClick={() => setSelectedAssetId(image.assetId)}
                className="aspect-square overflow-hidden rounded-lg bg-secondary motion-safe:transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <img
                  src={image.imageUrl}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="size-full object-cover"
                />
              </button>
              {(isCreatedAtVisible || hasUsageBadge) && (
                <figcaption className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
                  {isCreatedAtVisible && <time dateTime={image.createdAt}>{createdAtLabel}</time>}
                  {hasUsageBadge && (
                    <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
                      {image.usages.length}곳에서 사용 중
                    </span>
                  )}
                </figcaption>
              )}
            </figure>
          );
        })}
      </div>

      {selectedImage !== undefined && (
        <GeneratedImageDetailModal
          image={selectedImage}
          onClose={() => setSelectedAssetId(undefined)}
          onRestoreFocus={() => restoreFocusAfterDetail(selectedImage.assetId)}
          onUseAsReference={
            canUseAsReference
              ? () => {
                  closeReasonRef.current = { kind: "reference" };
                  setReference({ assetId: selectedImage.assetId, imageUrl: selectedImage.imageUrl });
                }
              : undefined
          }
          onDeleted={handleImageDeleted}
        />
      )}
    </>
  );
}

function LibraryGridSkeleton({ gridColumnsClassName }: { gridColumnsClassName: string }) {
  return (
    <div className={cn("grid gap-3", gridColumnsClassName)}>
      {[0, 1, 2, 3, 4, 5, 6, 7].map((key) => (
        <div key={key} className="flex flex-col gap-1.5">
          <div className="aspect-square animate-pulse rounded-lg bg-secondary" />
          <div className="h-3 w-16 animate-pulse rounded bg-secondary" />
        </div>
      ))}
    </div>
  );
}
