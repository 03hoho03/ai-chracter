import { isApiError } from "@/shared/api/client";

/** BE `require_legal_consent`(api/legal/dependencies.py)가
 * 쓰기 21곳에서 내는 403 `{"detail": {"code": "LEGAL_RECONSENT_REQUIRED", "kinds": [...]}}`를 판별한다.
 * `detail`이 string인 정지 403(`"Account suspended"`, is_user_suspended 선례)과 반드시 구분돼야
 * 하므로 `typeof detail === "object"`를 먼저 본다 — 좁히기 형태는
 * `EmailVerifyStep`(429의 retryAfterSeconds)·`publishRejection`(400의 reason/missingFields)과
 * 같다. */
export function isLegalReconsentRequiredError(error: unknown): boolean {
  const apiError = isApiError(error) ? error : undefined;
  if (apiError?.status !== 403 || !apiError.detail || typeof apiError.detail !== "object") return false;
  return apiError.detail.code === "LEGAL_RECONSENT_REQUIRED";
}
