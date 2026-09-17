import { Loader2 } from "lucide-react";

import type { ImageJobStatusResponse } from "@/entities/image-job";
import { assertNever } from "@/shared/lib/assertNever";

type GenerateImagesResultGridProps = {
  job: ImageJobStatusResponse | undefined;
  requestedCount: number;
  isQueryError: boolean;
}

type BlockedReason = NonNullable<ImageJobStatusResponse["blockedReason"]>;

// guard-goal-prompt.md G-4/G-6 — 서버는 blockedReason만 내리고 한국어 문구는 FE가 조립한다. 사유·
// 임계값은 노출하지 않는다(무엇이 얼마나 걸렸는지 알리면 이진 탐색으로 통과선을 찾을 수 있다).
// `prompt`는 표현을 바꾸라는 안내까지(판정이 결정적이라 같은 프롬프트 재시도는 무의미하다),
// `image`는 중립 문구만(사후 가드는 반복하면 언젠가 통과하므로 재시도를 암시하면 우회를 권하는 셈이다).
// 전부 차단(failed)에서만 쓴다 — 부분 차단 문구는 사유를 보지 않는다(아래 getPartialBlockNotice).
function getBlockedReasonCopy(reason: BlockedReason): string {
  switch (reason) {
    case "prompt":
      return "이 프롬프트로는 이미지를 만들 수 없어요. 문구를 바꿔서 다시 시도해주세요.";
    case "image":
      return "운영 정책에 따라 이 요청을 처리할 수 없어요.";
    default:
      return assertNever(reason);
  }
}

type InputError = NonNullable<ImageJobStatusResponse["inputError"]>;

// image-style-7-goal-prompt.md IS-8 — `input_error`는 `blockedReason`과 달리 사용자가 프롬프트를
// 고치면 통과할 수 있는 결정적 실패라 구체적으로 알려준다. `syntax`는 결정적이므로(계약 4-1: 문법을
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

// local-image-gen-contract.md LC-4b — 프롬프트 가드는 결정적이라 같은 프롬프트는 항상 전부-차단이다.
// 그래서 부분 차단(SUCCEEDED + blockedCount>0)은 이미지 가드에서만 나올 수 있고, 여기에 `prompt`
// 사유가 섞이면 상류(로컬 가드) 이상이다 — 그 경우에도 "문구를 바꿔주세요"는 G-4가 금지하는
// 거짓 안내가 되므로, 부분 차단 문구는 사유와 무관한 중립 문장 하나로 둔다.
function getPartialBlockNotice(count: number): string {
  return `${count}장은 운영 정책에 따라 표시하지 않았어요.`;
}

// US-008 — 폴링 상태를 그리드로 보여준다. 완료 전엔 남은 칸을 스켈레톤으로 채워 진행률을 드러내고,
// 완료(succeeded)되면 실제 결과만, 실패(failed)면 에러 메시지를 보여준다.
// 그리드 스타일은 select-generated-image/GeneratedImagePickerModal과 동일(grid-cols-3 gap-2 + aspect-square rounded-md bg-muted).
export function GenerateImagesResultGrid({
  job,
  requestedCount,
  isQueryError,
}: GenerateImagesResultGridProps) {
  if (isQueryError) {
    return (
      <p role="alert" className="text-sm text-destructive-text">
        진행 상황을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (!job) {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="size-4 animate-spin" />
          <span>생성 준비 중...</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {Array.from({ length: requestedCount }, (_, i) => (
            <div key={i} className="aspect-square animate-pulse rounded-md bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  if (job.status === "failed") {
    // guard-techspec.md GT-3 — 전부 차단이면 서버가 `error`를 비운다(문구는 FE가 조립한다, G-6).
    // 받은 이미지가 없는 실패 표면이므로 기존 failed 분기와 같은 취급(assertive alert)을 따른다(G-7).
    const blockedCopy = job.blockedCount > 0 && job.blockedReason != null
      ? getBlockedReasonCopy(job.blockedReason)
      : null;
    // image-style-7-goal-prompt.md IS-8 — 문법/길이 입력 오류는 결정적이라 blockedReason과
    // 동시에 나지 않는다(부분 input_error가 원리적으로 불가능한 것과 같은 이유).
    const inputErrorCopy = job.inputError != null ? getInputErrorCopy(job.inputError) : null;
    return (
      <p role="alert" className="text-sm text-destructive-text">
        {inputErrorCopy ?? blockedCopy ?? job.error ?? "이미지 생성에 실패했어요. 잠시 후 다시 시도해주세요."}
      </p>
    );
  }

  const isTerminal = job.status === "succeeded";
  const skeletonCount = isTerminal ? 0 : Math.max(job.requestedCount - job.images.length, 0);
  // guard-goal-prompt.md G-7 — 부분 차단은 실패가 아니라 정보다. 성공한 이미지 옆에 무채색 톤으로
  // 공존시키고(destructive 금지), aria-live="polite"로 알린다 — assertive면 이미지가 막 렌더되는
  // 순간 스크린리더를 끊고 끼어든다.
  const partialBlockNotice =
    isTerminal && job.blockedCount > 0 && job.blockedReason != null
      ? getPartialBlockNotice(job.blockedCount)
      : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        {!isTerminal && <Loader2 aria-hidden className="size-4 animate-spin" />}
        <span>
          {isTerminal
            ? `${job.images.length}장 생성 완료`
            : `${job.completedCount}/${job.requestedCount}장 생성 중...`}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {job.images.map((image) => (
          <div key={image.assetId} className="aspect-square overflow-hidden rounded-md bg-muted">
            <img
              src={image.imageUrl}
              alt=""
              loading="lazy"
              decoding="async"
              className="size-full object-cover"
            />
          </div>
        ))}
        {Array.from({ length: skeletonCount }, (_, i) => (
          <div key={`pending-${i}`} className="aspect-square animate-pulse rounded-md bg-muted" />
        ))}
      </div>
      {/* my-works/ui/MyWorksPage.tsx:507 선례 — polite 라이브 리전은 조건부로 마운트하면 announce
          여부가 스크린리더/브라우저 조합마다 갈린다(그 파일 주석의 실측 근거). 그래서 이 <p>는
          isTerminal이 아닌 동안(잡이 아직 진행 중일 때)부터 항상 DOM에 있고, 내용만 빈 문자열→
          문구로 바뀐다 — 완료 시점에 새 노드로 끼워 넣지 않는다. 아무것도 차단되지 않은 채
          끝나는 경우(오늘의 기본 화면)와 시각적으로 동일하도록 비어 있을 때는 sr-only로 접는다. */}
      <p
        aria-live="polite"
        className={partialBlockNotice ? "text-sm text-muted-foreground" : "sr-only"}
      >
        {partialBlockNotice}
      </p>
    </div>
  );
}
