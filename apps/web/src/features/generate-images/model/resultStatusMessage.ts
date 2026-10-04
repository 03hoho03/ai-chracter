import type { ImageJobStatusResponse } from "@/entities/image-job";

/** 문구를 고르는 데 필요한 잡 응답 조각. 이미지는 장수만 본다. */
export type ResultStatusJob = Pick<
  ImageJobStatusResponse,
  "status" | "completedCount" | "blockedCount" | "blockedReason"
> & { images: readonly unknown[] };

type ResultStatusInput = {
  /** 폼 제출이 진행 중인가(202 전 — 클로버 확인 모달을 기다리는 동안 포함). */
  isSubmitting: boolean;
  /** 202 를 받은 제출이 있는가. */
  hasSubmission: boolean;
  job: ResultStatusJob | undefined;
  /** 제출한 장수 — 첫 응답 전에도 분모가 있어야 한다. */
  requestedCount: number;
  hasPollError: boolean;
};

type ResultStatusMessage = {
  /** 화면에도 보이는 상태 글자. */
  status: string;
  /** 같은 live region 안에서 화면낭독기만 읽는 덧붙임(부분 차단 문장). 앞에 띄어쓰기를 포함한다. */
  srSuffix: string;
  /** 스피너를 붙일 진행 단계인가. */
  isInProgress: boolean;
};

const EMPTY: ResultStatusMessage = { status: "", srSuffix: "", isInProgress: false };

/** 결과 영역 머리 줄의 상태 문구 — 이 영역의 유일한 polite live region 이 그대로 읽는다.
 *
 * 요청 보내는 중 → 생성 중(0/m) → c/m장 생성 중 → n장 생성 완료의 네 단계다. 대기(queued)는 서버가
 * 곧바로 running 으로 바꿔 거의 보이지 않으므로 0장 진행과 같은 문구로 둔다. 제출 중이 가장 먼저인
 * 것은 직전 결과가 완료로 남아 있어도 새 요청이 나가고 있다는 사실이 지금의 상태이기 때문이다.
 *
 * 잡이 실패했거나 폴링이 오류로 끝나면 문구를 비운다 — 실패는 결과 영역의 `role="alert"` 가 알리고,
 * 상태 줄에 진행 문구(`1/2장 생성 중…`)가 남으면 화면이 거짓말을 한다. 다만 이미 받은 완료 결과는
 * 그 뒤의 조회 오류보다 앞선다(완료된 잡은 더 바뀌지 않는다). */
export function getResultStatusMessage({
  isSubmitting,
  hasSubmission,
  job,
  requestedCount,
  hasPollError,
}: ResultStatusInput): ResultStatusMessage {
  if (isSubmitting) return { status: "요청 보내는 중…", srSuffix: "", isInProgress: true };
  if (!hasSubmission) return EMPTY;

  if (job?.status === "succeeded") {
    const notice = getPartialBlockNotice(job);
    return {
      status: `${job.images.length}장 생성 완료`,
      srSuffix: notice === undefined ? "" : ` ${notice}`,
      isInProgress: false,
    };
  }
  if (job?.status === "failed" || hasPollError) return EMPTY;

  const completedCount = job?.completedCount ?? 0;
  return {
    status: completedCount > 0 ? `${completedCount}/${requestedCount}장 생성 중…` : `생성 중… (0/${requestedCount}장)`,
    srSuffix: "",
    isInProgress: true,
  };
}

/** 완료된 잡에서 일부가 차단됐을 때의 안내. 없으면 `undefined`.
 *
 * 프롬프트 가드는 결정적이라 같은 프롬프트는 항상 전부 차단이다. 부분 차단은 장마다 따로 검사되는
 * 가드(결과 이미지, 참조 이미지)에서 나오고, 어느 쪽이든 성공한 이미지 옆에서 "문구를 바꿔주세요"·
 * "다른 이미지를 골라 보세요"는 거짓 안내가 될 수 있으므로 사유와 무관한 중립 문장 하나로 둔다. */
export function getPartialBlockNotice(
  job: Pick<ImageJobStatusResponse, "status" | "blockedCount" | "blockedReason">,
): string | undefined {
  if (job.status !== "succeeded" || job.blockedCount <= 0 || job.blockedReason == null) return undefined;
  return `${job.blockedCount}장은 운영 정책에 따라 표시하지 않았어요.`;
}
