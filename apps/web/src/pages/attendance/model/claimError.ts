import { isIdentityVerificationRequiredError } from "@/entities/identity";
import { isApiError } from "@/shared/api/client";

/** 수령 요청의 실패를 화면이 할 일로 가른 갈래. */
export type ClaimErrorKind = "checking" | "paused" | "identity" | "off" | "failed";

function isCloverPausedError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 503) return false;
  if (!error.detail || typeof error.detail !== "object") return false;
  return error.detail.code === "CLOVER_PAUSED";
}

/** 수령 요청의 실패를 화면이 할 일로 가른다.
 *
 * - 응답이 없거나 서버 오류면 지급이 됐는지 모르므로 판을 다시 받아 확인한다(`checking`). 다시 눌러도 서버가 하루 한 번만
 *   지급해 이중 지급은 없다. API 클라이언트에 시간 제한이 없어 "시간 초과" 갈래는 따로 없다.
 * - 정지 스위치의 503 은 지급이 안 된 것이 확실해 확인하지 않는다. 같은 5xx 대역이라 그 밖의 서버 오류보다 먼저 가른다.
 * - 같은 403 을 쓰는 다른 거절(정지·재동의)은 인증 안내가 아니라 확정 실패다 — 재동의는 전역 모달이, 세션 소실은 전역
 *   처리가 따로 맡는다. 인증 403 뒤 세션 무효화도 전역 mutation 오류 처리가 이미 한다. */
export function classifyClaimError(error: unknown): ClaimErrorKind {
  if (!isApiError(error)) return "failed";
  if (error.status === 0) return "checking";
  if (isCloverPausedError(error)) return "paused";
  if (error.status >= 500) return "checking";
  if (isIdentityVerificationRequiredError(error)) return "identity";
  if (error.status === 404) return "off";
  return "failed";
}
