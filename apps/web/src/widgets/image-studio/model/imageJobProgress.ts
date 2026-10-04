import { isTerminalImageJobStatus, type ImageJobStatus } from "@/entities/image-job";

/** 지켜보는 잡이 아직 끝나지 않았는가 — 참이면 생성 버튼을 잠근다(서버가 사용자당 잡을 하나만 받아,
 * 끝나기 전에 다시 제출하면 429 로 끝난다).
 *
 * 첫 응답 전(`status` 없음)은 진행 중이다. 폴링이 오류로 끝났으면 잡이 어떤 상태인지 모르므로 풀어
 * 준다 — 잠근 채로 두면 다시 생성할 길이 없다. `hasPollError` 는 재조회 동안 깜빡이지 않는 신호
 * (`hasImageJobPollError`)여야 버튼이 잠겼다 풀렸다를 되풀이하지 않는다. */
export function isImageJobInProgress({
  hasSubmission,
  status,
  hasPollError,
}: {
  hasSubmission: boolean;
  status: ImageJobStatus | undefined;
  hasPollError: boolean;
}): boolean {
  return hasSubmission && !hasPollError && !isTerminalImageJobStatus(status);
}
