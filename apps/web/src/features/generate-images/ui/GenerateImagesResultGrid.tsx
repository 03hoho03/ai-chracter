import { useId } from "react";
import { Loader2 } from "lucide-react";
import { useFormContext, useFormState, useWatch } from "react-hook-form";

import type { ImageJobStatusResponse } from "@/entities/image-job";
import { assertNever } from "@/shared/lib/assertNever";

import { getResultTileLabel } from "../model/generateButtonState";
import { isEveryResultHidden } from "../model/remainingResults";
import { getPartialBlockNotice, getResultStatusMessage } from "../model/resultStatusMessage";
import { getResultTileLayout, type ResultShape } from "../model/resultTileLayout";
import type { GenerateImagesFormValues } from "../model/schema";

type GenerateImagesResultGridProps = {
  /** 마지막으로 202를 받은 제출의 비율·개수. 없으면 아직 생성한 적이 없는 빈 상태다. */
  shape: ResultShape | undefined;
  job: ImageJobStatusResponse | undefined;
  /** 잡 조회가 오류로 끝났는가 — 재조회 동안 깜빡이지 않는 신호(`hasImageJobPollError`)를 받는다. */
  hasPollError: boolean;
  /** 이 화면에서 삭제한 이미지. 그 칸은 빈 열로 남고, 받은 결과를 모두 지우면 빈 상태로 돌아간다. */
  hiddenAssetIds: ReadonlySet<string>;
  /** 상세를 열려고 목록 응답을 기다리는 타일. */
  openingAssetId: string | undefined;
  onSelectImage: (assetId: string) => void;
};

type BlockedReason = NonNullable<ImageJobStatusResponse["blockedReason"]>;

type InputError = NonNullable<ImageJobStatusResponse["inputError"]>;

type ResultImage = ImageJobStatusResponse["images"][number];

// 중앙 열의 결과 영역. 생성 화면에 늘 마운트돼 있고 한 섹션 안에서 빈 상태 → 진행 → 결과(또는 실패)를
// 그린다. 결과를 언제 바꿀지는 이 컴포넌트가 아니라 제출을 소유한 셸이 정한다(`shape`·`job`을 바꿔 준다).
// 결과 타일을 눌렀을 때 상세를 여는 일도 호출부 몫이다(모달은 이 슬라이스 위 계층에 있다).
//
// 칸 모양은 `getResultTileLayout` 하나가 정한다 — 열 수 = 장수, 비율 = 제출한 비율, 높이 상한은 열 폭에
// 건다. 빈 상태 칸·스켈레톤·결과 타일이 같은 값을 쓰므로 결과가 도착해도 칸이 움직이지 않는다.
// 빈 상태는 폼의 **현재** 비율·개수로 그려, 생성 전에 고른 설정이 어떤 모양으로 나올지 미리 보인다.
export function GenerateImagesResultGrid({
  shape,
  job,
  hasPollError,
  hiddenAssetIds,
  openingAssetId,
  onSelectImage,
}: GenerateImagesResultGridProps) {
  const headingId = useId();
  const { control } = useFormContext<GenerateImagesFormValues>();
  const { isSubmitting } = useFormState({ control });
  const formAspectRatio = useWatch({ control, name: "aspectRatio" });
  const formCount = useWatch({ control, name: "count" });

  // 받은 결과를 모두 지웠으면 첫 생성 전과 같은 빈 상태로 되돌린다 — 완료 문구와 부분 차단 안내도
  // 함께 비운다(둘 다 이제 화면에 없는 결과에 대한 말이다). 일부만 지웠으면 그 칸은 빈 열로 남는다.
  const isCleared =
    shape !== undefined &&
    job !== undefined &&
    isEveryResultHidden({ job, requestedCount: shape.count, hasPollError, hiddenAssetIds });
  const visibleShape = isCleared ? undefined : shape;

  const message = getResultStatusMessage({
    isSubmitting,
    hasSubmission: visibleShape !== undefined,
    job,
    requestedCount: shape?.count ?? 0,
    hasPollError,
  });
  // 부분 차단은 실패가 아니라 정보다. 성공한 이미지 아래 무채색 톤으로 공존시킨다(destructive 금지).
  // 화면 문장은 `aria-hidden` 이고, 같은 문장은 상태 줄 live region 안에서 완료 문구와 한 번에 읽힌다.
  const partialBlockNotice = visibleShape !== undefined && job !== undefined ? getPartialBlockNotice(job) : undefined;

  return (
    // relative — 이 안에 absolute 조각(sr-only 등)이 생겨도 그 기준이 이 섹션이 되어 중앙 스크롤러
    // 안에 머문다. 기준이 될 조상이 없으면 lg 이상의 중앙 스크롤러(`overflow-y-auto`, positioned 아님)
    // 바깥이 기준이 되어 그 조각이 문서 높이를 늘리고 페이지 전체가 스크롤된다(실제로 그랬다).
    <section aria-labelledby={headingId} className="relative flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        {/* 같은 열의 입력 라벨(`text-sm font-medium`)보다 한 단계 굵게 — 입력과 출력의 경계를
            크기를 바꾸지 않고 굵기로만 긋는다. `tabIndex={-1}`은 Tab 순서에 넣지 않고 프로그램 포커스만
            받게 한다 — 상세에서 마지막 결과를 지워 돌아갈 타일이 없을 때 포커스를 둘 자리다. */}
        <h2
          id={headingId}
          tabIndex={-1}
          className="text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          생성 결과
        </h2>
        {/* 이 영역의 유일한 live region. 진행 문구와 부분 차단 문장을 한 노드에 담아, 완료와 차단이
            따로 두 번이 아니라 한 번에 읽힌다. polite 라이브 리전은 조건부로 마운트하면 announce 여부가
            스크린리더/브라우저 조합마다 갈린다는 것이 업계 통설이라(이 파일에서 실측한 적은 없다) 늘
            마운트해 두고 내용만 바꾼다(`MyWorksPage`·`GenerateImagesPromptField` 의 polite 영역과 같은
            방식). 머리 줄 안의 in-flow 문단이라 비어 있어도 아래에 여백을 만들지 않는다. sr-only 조각은
            absolute 라 이 문단을 기준(relative)으로 묶는다. `aria-atomic` 은 완료 문구와 차단 문장이 따로
            바뀐 조각으로 읽히지 않고 문단 전체로 한 번에 읽히게 한다. 스피너는 진행 표시라 모션 감소
            설정에서도 끄지 않는다. */}
        <p aria-live="polite" aria-atomic className="relative flex items-center gap-2 text-sm text-muted-foreground">
          {message.isInProgress && <Loader2 aria-hidden className="size-4 animate-spin" />}
          {message.status}
          <span className="sr-only">{message.srSuffix}</span>
        </p>
      </div>

      {visibleShape === undefined ? (
        <EmptyResultCells shape={{ aspectRatio: formAspectRatio, count: formCount }} />
      ) : (
        <ResultBody
          shape={visibleShape}
          job={job}
          hasPollError={hasPollError}
          hiddenAssetIds={hiddenAssetIds}
          openingAssetId={openingAssetId}
          onSelectImage={onSelectImage}
        />
      )}

      {partialBlockNotice !== undefined && (
        <p aria-hidden className="text-xs text-muted-foreground">
          {partialBlockNotice}
        </p>
      )}
    </section>
  );
}

// 첫 생성 전(또는 받은 결과를 모두 지운 뒤)의 자리표시. 점선은 "보여 줄 내용이 없는 자리"의
// 어휘이고(DESIGN.md Components 절의 Empty state), 채움이 없어 진행 중 스켈레톤(채움 + 펄스)과 모양으로 갈린다. 점선은 장식 구분선이라
// 3:1 요건이 없고, 뜻은 첫 칸의 안내 글자가 진다.
function EmptyResultCells({ shape }: { shape: ResultShape }) {
  const layout = getResultTileLayout(shape.aspectRatio, shape.count);

  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: layout.gridTemplateColumns }}>
      {Array.from({ length: shape.count }, (_, i) => (
        <div
          key={i}
          className="flex items-center justify-center rounded-lg border border-dashed border-border p-3"
          style={{ aspectRatio: layout.aspectRatio }}
        >
          {i === 0 && (
            <p className="text-center text-xs break-keep text-muted-foreground">생성한 이미지가 여기에 나와요</p>
          )}
        </div>
      ))}
    </div>
  );
}

function ResultBody({
  shape,
  job,
  hasPollError,
  hiddenAssetIds,
  openingAssetId,
  onSelectImage,
}: {
  shape: ResultShape;
  job: ImageJobStatusResponse | undefined;
  hasPollError: boolean;
  hiddenAssetIds: ReadonlySet<string>;
  openingAssetId: string | undefined;
  onSelectImage: (assetId: string) => void;
}) {
  // 터미널 응답이 먼저다 — 완료·실패한 잡은 더 바뀌지 않으므로, 그 뒤의 조회 오류가 이미 받은 결과를
  // 덮지 않는다.
  if (job?.status === "failed") {
    return (
      <p role="alert" className="text-sm text-destructive-text">
        {getFailedJobCopy(job)}
      </p>
    );
  }

  if (hasPollError && job?.status !== "succeeded") {
    return (
      <p role="alert" className="text-sm text-destructive-text">
        진행 상황을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const layout = getResultTileLayout(shape.aspectRatio, shape.count);
  const images = job?.images ?? [];
  const isSucceeded = job?.status === "succeeded";
  // 완료 전엔 남은 칸을 스켈레톤으로 채워 진행률을 드러낸다. 완료되면 받은 이미지만 남긴다 —
  // 부분 차단으로 빠진 칸과 지운 칸은 열 수가 그대로라 빈 열로 남는다. 스켈레톤 수는 지우기 전 장수로
  // 세어, 진행 중에 한 장을 지워도 그 자리가 다시 "생성 중"으로 돌아가지 않는다.
  const skeletonCount = isSucceeded ? 0 : Math.max(shape.count - images.length, 0);

  // 칸 바탕은 `muted`가 아니라 `secondary`다. 둘 다 페이지 배경 위지만 `muted`는 배경 대비 약 1.09:1이라
  // 다크에서 펄스하는 스켈레톤이 빈 칸처럼 보였고, `secondary`는 다크 1.25 · 라이트 1.23:1로 면이 읽힌다.
  return (
    <div aria-busy={!isSucceeded} className="grid gap-2" style={{ gridTemplateColumns: layout.gridTemplateColumns }}>
      {images.map((image, index) =>
        hiddenAssetIds.has(image.assetId) ? null : (
          <ResultTile
            key={image.assetId}
            image={image}
            label={getResultTileLabel(index + 1, shape.count)}
            aspectRatio={layout.aspectRatio}
            isOpening={openingAssetId === image.assetId}
            onSelect={onSelectImage}
          />
        ),
      )}
      {Array.from({ length: skeletonCount }, (_, i) => (
        <div
          key={`pending-${i}`}
          className="animate-pulse rounded-lg bg-secondary"
          style={{ aspectRatio: layout.aspectRatio }}
        />
      ))}
    </div>
  );
}

// 결과 한 장 = 상세를 여는 버튼. 칸 번호는 지우기 전 순서로 세어, 한 장을 지워도 남은 칸의 이름이
// 바뀌지 않는다. 분모는 요청한 장수라 진행 중에 먼저 나온 칸도 "1/2" 로 읽힌다.
//
// 포커스는 하우스 레시피(투명 1px 보더 → `border-ring` + 50% 링)다. 50% 링만으로는 배경 대비 3:1 에
// 못 미치고 불투명 보더가 그 몫을 진다(DESIGN.md Buttons 절 Focus). hover 는 보관함 타일과 같은 흐림이다.
//
// `loading="lazy"`를 걸지 않는다 — 제출 직후 사용자가 바로 그 자리를 보고 있는 이미지라 늦출 까닭이
// 없다. 디코딩만 비동기로 둔다.
//
// 상세를 열려고 목록을 기다리는 동안은 칸 가운데 스크림 위 스피너로 알린다(채운 그림 위라 스크림 쌍이
// 대비를 진다, 진행 표시라 모션을 끄지 않는다).
function ResultTile({
  image,
  label,
  aspectRatio,
  isOpening,
  onSelect,
}: {
  image: ResultImage;
  label: string;
  aspectRatio: string;
  isOpening: boolean;
  onSelect: (assetId: string) => void;
}) {
  return (
    <button
      type="button"
      data-generate-images-result-tile={image.assetId}
      aria-label={label}
      aria-busy={isOpening}
      onClick={() => onSelect(image.assetId)}
      className="relative w-full overflow-hidden rounded-lg border border-transparent bg-secondary motion-safe:transition-opacity hover:opacity-80 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
      style={{ aspectRatio }}
    >
      <img src={image.imageUrl} alt="" decoding="async" className="size-full object-cover" />
      {isOpening && (
        <span className="pointer-events-none absolute inset-0 m-auto inline-flex size-7 items-center justify-center rounded-full bg-scrim/70 text-scrim-foreground">
          <Loader2 aria-hidden className="size-4 animate-spin" />
        </span>
      )}
    </button>
  );
}

function getFailedJobCopy(job: ImageJobStatusResponse): string {
  // 전부 차단이면 서버가 `error`를 비운다(문구는 FE가 조립한다).
  // 받은 이미지가 없는 실패 표면이므로 기존 failed 분기와 같은 취급(assertive alert)을 따른다.
  const blockedCopy =
    job.blockedCount > 0 && job.blockedReason != null ? getBlockedReasonCopy(job.blockedReason) : undefined;
  // 문법/길이 입력 오류는 결정적이라 blockedReason과
  // 동시에 나지 않는다(부분 input_error가 원리적으로 불가능한 것과 같은 이유).
  const inputErrorCopy = job.inputError != null ? getInputErrorCopy(job.inputError) : undefined;
  return inputErrorCopy ?? blockedCopy ?? job.error ?? "이미지 생성에 실패했어요. 잠시 후 다시 시도해주세요.";
}

// 서버는 blockedReason만 내리고 한국어 문구는 FE가 조립한다. 사유·
// 임계값은 노출하지 않는다(무엇이 얼마나 걸렸는지 알리면 이진 탐색으로 통과선을 찾을 수 있다).
// `prompt`는 표현을 바꾸라는 안내까지(판정이 결정적이라 같은 프롬프트 재시도는 무의미하다),
// `image`는 중립 문구만(사후 가드는 반복하면 언젠가 통과하므로 재시도를 암시하면 우회를 권하는 셈이다).
// `reference`는 참조 이미지를 짚어 다른 이미지를 고르라고 안내한다 — 원인 축이 이미지 하나라 명시해도
// 통과선 탐색 위험이 작고, 같은 참조로 재시도를 암시하는 말은 붙이지 않는다.
// 전부 차단(failed)에서만 쓴다 — 부분 차단 문구는 사유를 보지 않는다(`getPartialBlockNotice`).
function getBlockedReasonCopy(reason: BlockedReason): string {
  switch (reason) {
    case "prompt":
      return "이 프롬프트로는 이미지를 만들 수 없어요. 문구를 바꿔서 다시 시도해주세요.";
    case "image":
      return "운영 정책에 따라 이 요청을 처리할 수 없어요.";
    case "reference":
      return "이 참조 이미지로는 만들 수 없어요. 다른 이미지를 골라 보세요.";
    default:
      return assertNever(reason);
  }
}

// `input_error`는 `blockedReason`과 달리 사용자가 프롬프트를
// 고치면 통과할 수 있는 결정적 실패라 구체적으로 알려준다. `syntax`는 결정적이므로(문법을
// 고쳐야 통과한다) "다시 시도해주세요"를 붙이지 않는다 — 재시도를 암시하면 거짓 안내가 된다.
function getInputErrorCopy(inputError: InputError): string {
  switch (inputError) {
    case "too_long":
      return "프롬프트가 너무 길어요. 문구를 줄여서 다시 시도해주세요.";
    case "syntax":
      return "프롬프트 문법을 확인해주세요.";
    default:
      return assertNever(inputError);
  }
}
