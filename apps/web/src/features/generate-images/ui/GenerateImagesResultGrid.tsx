import { useId } from "react";
import { Loader2 } from "lucide-react";
import { useFormContext, useWatch } from "react-hook-form";

import type { ImageJobStatusResponse } from "@/entities/image-job";
import { assertNever } from "@/shared/lib/assertNever";

import { getResultTileLayout, type ResultShape } from "../model/resultTileLayout";
import type { GenerateImagesFormValues } from "../model/schema";

type GenerateImagesResultGridProps = {
  /** 마지막으로 202를 받은 제출의 비율·개수. 없으면 아직 생성한 적이 없는 빈 상태다. */
  shape: ResultShape | undefined;
  job: ImageJobStatusResponse | undefined;
  isQueryError: boolean;
};

type BlockedReason = NonNullable<ImageJobStatusResponse["blockedReason"]>;

type InputError = NonNullable<ImageJobStatusResponse["inputError"]>;

// 중앙 열의 결과 영역. 생성 화면에 늘 마운트돼 있고 한 섹션 안에서 빈 상태 → 진행 → 결과(또는 실패)를
// 그린다. 결과를 언제 바꿀지는 이 컴포넌트가 아니라 제출을 소유한 셸이 정한다(`shape`·`job`을 바꿔 준다).
//
// 칸 모양은 `getResultTileLayout` 하나가 정한다 — 열 수 = 장수, 비율 = 제출한 비율, 높이 상한은 열 폭에
// 건다. 빈 상태 칸·스켈레톤·결과 타일이 같은 값을 쓰므로 결과가 도착해도 칸이 움직이지 않는다.
// 빈 상태는 폼의 **현재** 비율·개수로 그려, 생성 전에 고른 설정이 어떤 모양으로 나올지 미리 보인다.
export function GenerateImagesResultGrid({ shape, job, isQueryError }: GenerateImagesResultGridProps) {
  const headingId = useId();
  const { control } = useFormContext<GenerateImagesFormValues>();
  const formAspectRatio = useWatch({ control, name: "aspectRatio" });
  const formCount = useWatch({ control, name: "count" });

  // 부분 차단은 실패가 아니라 정보다. 성공한 이미지 옆에 무채색 톤으로
  // 공존시키고(destructive 금지), aria-live="polite"로 알린다 — assertive면 이미지가 막 렌더되는
  // 순간 스크린리더를 끊고 끼어든다.
  const partialBlockNotice =
    shape !== undefined && job?.status === "succeeded" && job.blockedCount > 0 && job.blockedReason != null
      ? getPartialBlockNotice(job.blockedCount)
      : undefined;

  return (
    // relative — 이 안에 absolute 조각(sr-only 등)이 생겨도 그 기준이 이 섹션이 되어 중앙 스크롤러
    // 안에 머문다. 기준이 될 조상이 없으면 lg 이상의 중앙 스크롤러(`overflow-y-auto`, positioned 아님)
    // 바깥이 기준이 되어 그 조각이 문서 높이를 늘리고 페이지 전체가 스크롤된다(실제로 그랬다).
    <section aria-labelledby={headingId} className="relative flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        {/* 같은 열의 입력 라벨(`text-sm font-medium`)보다 한 단계 굵게 — 입력과 출력의 경계를
            크기를 바꾸지 않고 굵기로만 긋는다. */}
        <h2 id={headingId} className="text-sm font-semibold">
          생성 결과
        </h2>
        {shape !== undefined && !isQueryError && job?.status !== "failed" && <ResultStatusLine job={job} />}
      </div>

      {shape === undefined ? (
        <EmptyResultCells shape={{ aspectRatio: formAspectRatio, count: formCount }} />
      ) : (
        <ResultBody shape={shape} job={job} isQueryError={isQueryError} />
      )}

      {/* polite 라이브 리전은 조건부로 마운트하면 announce 여부가 스크린리더/브라우저 조합마다
          갈린다는 것이 업계 통설이다(이 파일에서 실측한 적은 없다) — 이 저장소의 polite 영역
          (MyWorksPage·GenerateImagesPromptField 등)이 항상 마운트해 두고 내용만 바꾸는 것도 그 통설을
          따른 것이다. 그래서 이 <p>는 결과 영역과 함께 늘 DOM에 있고 내용만 빈 문자열 → 문구로 바뀐다.
          비어 있을 때 sr-only로 접지 않는다 — sr-only는 absolute라 위 섹션 주석의 넘침을 만든 장본인이었고,
          글자가 없는 in-flow 문단은 높이가 0이라 접을 필요도 없다. */}
      <p aria-live="polite" className="text-sm text-muted-foreground">
        {partialBlockNotice}
      </p>
    </section>
  );
}

// 머리 줄 오른쪽의 진행·완료 문구.
function ResultStatusLine({ job }: { job: ImageJobStatusResponse | undefined }) {
  const isInProgress = job?.status !== "succeeded";
  const text = getStatusText(job);

  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      {isInProgress && <Loader2 aria-hidden className="size-4 animate-spin" />}
      {text}
    </p>
  );
}

function getStatusText(job: ImageJobStatusResponse | undefined): string {
  if (job === undefined) return "생성 준비 중...";
  if (job.status === "succeeded") return `${job.images.length}장 생성 완료`;
  return `${job.completedCount}/${job.requestedCount}장 생성 중...`;
}

// 첫 생성 전의 자리표시. 점선은 "보여 줄 내용이 없는 자리"의 어휘이고(DESIGN.md Components 절의
// Empty state), 채움이 없어 진행 중 스켈레톤(채움 + 펄스)과 모양으로 갈린다. 점선은 장식 구분선이라
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
  isQueryError,
}: {
  shape: ResultShape;
  job: ImageJobStatusResponse | undefined;
  isQueryError: boolean;
}) {
  if (isQueryError) {
    return (
      <p role="alert" className="text-sm text-destructive-text">
        진행 상황을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (job?.status === "failed") {
    return (
      <p role="alert" className="text-sm text-destructive-text">
        {getFailedJobCopy(job)}
      </p>
    );
  }

  const layout = getResultTileLayout(shape.aspectRatio, shape.count);
  const images = job?.images ?? [];
  // 완료 전엔 남은 칸을 스켈레톤으로 채워 진행률을 드러낸다. 완료되면 받은 이미지만 남긴다 —
  // 부분 차단으로 빠진 칸은 열 수가 그대로라 빈 열로 남는다.
  const skeletonCount = job?.status === "succeeded" ? 0 : Math.max(shape.count - images.length, 0);

  // 칸 바탕은 `muted`가 아니라 `secondary`다. 둘 다 페이지 배경 위지만 `muted`는 배경 대비 약 1.09:1이라
  // 다크에서 펄스하는 스켈레톤이 빈 칸처럼 보였고, `secondary`는 다크 1.25 · 라이트 1.23:1로 면이 읽힌다.
  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: layout.gridTemplateColumns }}>
      {images.map((image) => (
        <div
          key={image.assetId}
          className="overflow-hidden rounded-lg bg-secondary"
          style={{ aspectRatio: layout.aspectRatio }}
        >
          <img src={image.imageUrl} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
        </div>
      ))}
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
// 전부 차단(failed)에서만 쓴다 — 부분 차단 문구는 사유를 보지 않는다(아래 getPartialBlockNotice).
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

// 프롬프트 가드는 결정적이라 같은 프롬프트는 항상 전부-차단이다.
// 그래서 부분 차단(SUCCEEDED + blockedCount>0)에 `prompt` 사유가 섞이면 상류(로컬 가드) 이상이다.
// 부분 차단은 장마다 따로 검사되는 가드(결과 이미지, 참조 이미지)에서 나오고, 어느 쪽이든 성공한
// 이미지 옆에서 "문구를 바꿔주세요"·"다른 이미지를 골라 보세요"는 거짓 안내가 될 수 있으므로,
// 부분 차단 문구는 사유와 무관한 중립 문장 하나로 둔다.
function getPartialBlockNotice(count: number): string {
  return `${count}장은 운영 정책에 따라 표시하지 않았어요.`;
}
