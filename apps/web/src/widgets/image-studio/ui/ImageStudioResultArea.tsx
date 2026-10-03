import { useEffect, useEffectEvent, useRef, useState, type RefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  generatedImagesKeys,
  useGeneratedImagesQuery,
  type GeneratedImageItem,
} from "@/entities/generated-image";
import type { ImageJobStatusResponse } from "@/entities/image-job";
import { GenerateImagesResultGrid, useGenerateImagesSubmit, type ResultShape } from "@/features/generate-images";

import { GeneratedImageDetailModal } from "./GeneratedImageDetailModal";

type ImageStudioResultAreaProps = {
  /** 마지막으로 202를 받은 제출의 비율·개수. 없으면 빈 상태다. */
  shape: ResultShape | undefined;
  job: ImageJobStatusResponse | undefined;
  hasPollError: boolean;
  /** 이 화면의 상세 모달(결과·보관함)에서 지운 이미지. */
  hiddenAssetIds: ReadonlySet<string>;
  /** 지운 이미지나 목록에서 찾지 못한 이미지를 셸의 삭제 집합에 넣는다. */
  onImageDeleted: (assetId: string) => void;
  /** 결과 영역을 감싼 요소. 마지막 결과를 지워 돌아갈 타일이 없을 때 이 안의 결과 제목으로 포커스를 보낸다. */
  containerRef: RefObject<HTMLElement | null>;
};

// 상세 모달이 왜 닫혔는지. 닫힌 뒤 포커스를 둘 곳이 이유마다 다르고 모달은 그 이유를 모르므로, 닫기
// 직전에 적어 두고 닫힘 처리에서 읽은 뒤 지운다(보관함 패널과 같은 방식).
type DetailCloseReason =
  | { kind: "dismiss" }
  | { kind: "reference" }
  // 지운 타일은 사라지므로 지우기 직전에 다음·이전 타일을 골라 둔다.
  | { kind: "deleted"; neighborAssetIds: string[] };

type DetailLookupOutcome = "found" | "missing" | "failed";

// 중앙 결과 영역. 표현(그리드·문구)은 feature 의 `GenerateImagesResultGrid` 가 그리고, 여기는 결과를
// 눌렀을 때의 상세 모달·참조로 쓰기·삭제·닫힘 포커스를 맡는다 — 모달이 이 계층에 있어 feature 가 직접
// 열 수 없다.
//
// 잡 응답의 이미지는 상세 모달이 받는 보관함 항목(사용처·생성일 포함)이 아니라서, 상세는 보관함 목록에서
// `assetId` 로 찾아 연다. 그 목록을 읽는 관찰자는 결과를 고른 동안만 마운트되는 자식(`ResultImageDetailHost`)
// 안에 둔다. 목록 쿼리는 서명 URL 이 담겨 관찰자가 없으면 곧바로 캐시에서 지워지는데, 비활성 관찰자도
// 구독만 하고 있으면 그 삭제를 막는다 — 이 영역에 관찰자를 상시로 두면 좁은 화면에서 보관함 시트를 닫아도
// 목록이 남아, 다음에 시트를 열 때 낡은 목록이 먼저 그려진다.
export function ImageStudioResultArea({
  shape,
  job,
  hasPollError,
  hiddenAssetIds,
  onImageDeleted,
  containerRef,
}: ImageStudioResultAreaProps) {
  const queryClient = useQueryClient();
  const { isReferenceEnabled, unavailableReason, setReference, focusReferenceField } = useGenerateImagesSubmit();
  const canUseAsReference = isReferenceEnabled && unavailableReason === undefined;
  const [selectedAssetId, setSelectedAssetId] = useState<string>();
  // 상세를 열려고 목록 응답을 기다리는 타일. 찾았는지는 자식 안의 쿼리 값이라 이 렌더에서 파생할 수
  // 없어, 누를 때 켜고 자식이 판정을 알려 올 때 끈다.
  const [openingAssetId, setOpeningAssetId] = useState<string>();
  const closeReasonRef = useRef<DetailCloseReason>({ kind: "dismiss" });

  const visibleAssetIds = (job?.images ?? [])
    .map((image) => image.assetId)
    .filter((assetId) => !hiddenAssetIds.has(assetId));

  function getNeighborAssetIds(assetId: string): string[] {
    const index = visibleAssetIds.indexOf(assetId);
    if (index < 0) return [];
    return [visibleAssetIds[index + 1], visibleAssetIds[index - 1]].filter((id): id is string => id !== undefined);
  }

  function handleSelectImage(assetId: string) {
    setSelectedAssetId(assetId);
    // 넓은 화면은 좌열 보관함이 목록을 쥐고 있어 대개 바로 열린다. 목록에 아직 없으면(좁은 화면이라
    // 캐시가 없거나, 새 결과가 목록 재조회 전이면) 응답을 기다리는 동안 타일에 진행 표시를 건다.
    const cachedImages = queryClient.getQueryData<GeneratedImageItem[]>(generatedImagesKeys.list());
    setOpeningAssetId(cachedImages?.some((image) => image.assetId === assetId) ? undefined : assetId);
  }

  function focusResultTileOrHeading(assetIds: string[]) {
    const tile = assetIds
      .map((id) => document.querySelector<HTMLElement>(`[data-generate-images-result-tile="${id}"]`))
      .find((element) => element !== null);
    (tile ?? containerRef.current?.querySelector<HTMLElement>("h2"))?.focus();
  }

  // 모달은 트리거 없이 열려 스스로는 돌아갈 곳이 없다(닫히면 `<body>`). 일반 닫기는 연 타일로, 참조로
  // 쓰기는 방금 채운 참조 필드로, 삭제는 남은 이웃 타일로 보내고 하나도 안 남으면 결과 제목으로 간다.
  function restoreFocusAfterDetail(openedAssetId: string) {
    const reason = closeReasonRef.current;
    closeReasonRef.current = { kind: "dismiss" };
    if (reason.kind === "reference") {
      focusReferenceField();
      return;
    }
    focusResultTileOrHeading(reason.kind === "deleted" ? reason.neighborAssetIds : [openedAssetId]);
  }

  function handleImageDeleted(assetId: string) {
    closeReasonRef.current = { kind: "deleted", neighborAssetIds: getNeighborAssetIds(assetId) };
    onImageDeleted(assetId);
  }

  function handleLookupResolved(assetId: string, outcome: DetailLookupOutcome) {
    if (outcome === "found") {
      setOpeningAssetId(undefined);
      return;
    }
    // 이 모달에서 방금 지운 이미지는 모달이 목록 캐시에서 먼저 빼서 "못 찾음"으로 보인다. 그 닫힘과
    // 포커스는 삭제 흐름이 이미 정했다.
    if (closeReasonRef.current.kind === "deleted") return;

    const wasDetailShown = openingAssetId !== assetId;
    setSelectedAssetId(undefined);
    setOpeningAssetId(undefined);

    // 목록을 못 받았으면 이미지가 있는지 모른다 — 지운 것으로 치지 않고 타일을 남겨 다시 누를 수 있게 한다.
    if (outcome === "failed") {
      toast.error("이미지를 불러오지 못했어요. 잠시 후 다시 시도해주세요.");
      return;
    }

    // 다시 받은 목록에도 없으면 다른 탭이나 기기에서 지운 이미지다. 결과에서도 빼고 알린다.
    const neighborAssetIds = getNeighborAssetIds(assetId);
    onImageDeleted(assetId);
    toast.error("이미지를 찾지 못했어요. 삭제됐을 수 있어요.");
    if (wasDetailShown) {
      // 모달은 이미지가 목록에서 빠지는 순간 이미 내려갔고, 그 닫힘 처리가 다음 프레임에 이 값을 읽는다.
      closeReasonRef.current = { kind: "deleted", neighborAssetIds };
      return;
    }
    // 모달이 열리기 전이면 포커스는 누른 타일에 있었고 그 타일이 사라진다. 그사이 다른 곳으로 옮겼다면
    // 건드리지 않는다.
    requestAnimationFrame(() => {
      if (document.activeElement === null || document.activeElement === document.body) {
        focusResultTileOrHeading(neighborAssetIds);
      }
    });
  }

  return (
    <>
      <GenerateImagesResultGrid
        shape={shape}
        job={job}
        hasPollError={hasPollError}
        hiddenAssetIds={hiddenAssetIds}
        openingAssetId={openingAssetId}
        onSelectImage={handleSelectImage}
      />
      {selectedAssetId !== undefined && (
        // key — 다른 결과를 고르면 관찰자를 새로 마운트해 "마운트 뒤 응답을 받았는가"를 처음부터 센다.
        // 같은 관찰자를 이어 쓰면 직전 이미지 때 받은 응답으로 새 이미지를 곧바로 "못 찾음"으로 판정한다.
        <ResultImageDetailHost
          key={selectedAssetId}
          assetId={selectedAssetId}
          onResolved={(outcome) => handleLookupResolved(selectedAssetId, outcome)}
          onClose={() => setSelectedAssetId(undefined)}
          onRestoreFocus={() => restoreFocusAfterDetail(selectedAssetId)}
          onUseAsReference={
            canUseAsReference
              ? (image) => {
                  closeReasonRef.current = { kind: "reference" };
                  setReference({ assetId: image.assetId, imageUrl: image.imageUrl });
                }
              : undefined
          }
          onDeleted={handleImageDeleted}
        />
      )}
    </>
  );
}

type ResultImageDetailHostProps = {
  assetId: string;
  onResolved: (outcome: DetailLookupOutcome) => void;
  onClose: () => void;
  onRestoreFocus: () => void;
  onUseAsReference: ((image: GeneratedImageItem) => void) | undefined;
  onDeleted: (assetId: string) => void;
};

// 고른 결과를 보관함 목록에서 찾아 상세 모달을 띄운다. 찾으면 열고, 이 마운트 뒤 응답을 받고도 없으면
// 한 번 더 받아 보고 그래도 없을 때만 "못 찾음"(조회 오류면 "실패")으로 알린다. 마운트 뒤 응답을 기다리는
// 이유는 캐시의 목록이 낡았을 수 있어서다 — 새 결과는 잡이 끝난 뒤의 목록 재조회가 돌아오기 전까지
// 목록에 없으므로, 캐시만 보고 판정하면 방금 만든 결과를 지운 것으로 친다. 넓은 화면은 캐시에 목록이
// 있어 마운트하자마자 열리고(마운트가 배경 재조회 1건을 내지만 모달은 그 응답을 기다리지 않는다), 좁은
// 화면은 마운트가 첫 조회를 낸다.
//
// 한 번 더 받는 이유: 마운트할 때 목록 조회가 이미 진행 중이면 새 요청을 내지 않고 그 요청에 합류하는데,
// 그 요청은 이 이미지가 저장되기 전에 목록을 읽었을 수 있다(진행 중에 앞 타일을 눌러 낸 조회가 돌아오기
// 전에 다음 타일이 나와 그걸 누른 경우). 그 응답만 보고 판정하면 방금 나온 결과를 지운 것으로 친다.
// 다시 받는 요청은 이 마운트 뒤에 시작하므로 그 사이 저장된 이미지를 반드시 담는다. 다시 받는 것은
// 한 번 찾기 전에 한 번뿐이라 재조회가 이어지지 않고, 찾은 경우에는 요청이 늘지 않는다.
function ResultImageDetailHost({
  assetId,
  onResolved,
  onClose,
  onRestoreFocus,
  onUseAsReference,
  onDeleted,
}: ResultImageDetailHostProps) {
  const galleryQuery = useGeneratedImagesQuery(true);
  const image = galleryQuery.data?.find((item) => item.assetId === assetId);
  const isFound = image !== undefined;
  const { isFetchedAfterMount, isFetching, isError } = galleryQuery;
  const reportOutcome = useEffectEvent(onResolved);
  const refetchGallery = useEffectEvent(() => {
    // 아래 효과는 조회가 멈춘 뒤에만 부르지만, 그 사이 다른 조회(창 포커스 등)가 시작됐다면 언제
    // 시작했는지 따지지 않고 끊고 새로 낸다.
    void galleryQuery.refetch({ cancelRefetch: true });
  });
  // 한 번 찾은 뒤 사라졌다면 그 응답은 찾았던 목록보다 나중 요청이라 정말 지워진 것이다 — 다시 받지
  // 않는다. 다시 받으면 그동안 모달은 이미 내려가 연 타일로 포커스를 돌려 두고, 늦게 온 판정이 그
  // 타일을 지워 포커스가 `<body>`로 떨어진다.
  const canRefetchRef = useRef(true);

  useEffect(() => {
    if (isFound) {
      canRefetchRef.current = false;
      reportOutcome("found");
      return;
    }
    if (!isFetchedAfterMount || isFetching) return;
    if (isError) {
      reportOutcome("failed");
      return;
    }
    if (canRefetchRef.current) {
      canRefetchRef.current = false;
      refetchGallery();
      return;
    }
    reportOutcome("missing");
  }, [isFound, isFetchedAfterMount, isFetching, isError]);

  if (image === undefined) return null;

  return (
    <GeneratedImageDetailModal
      image={image}
      onClose={onClose}
      onRestoreFocus={onRestoreFocus}
      onUseAsReference={onUseAsReference && (() => onUseAsReference(image))}
      onDeleted={onDeleted}
    />
  );
}
