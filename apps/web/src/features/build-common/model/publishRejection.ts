import { isApiError } from "@/shared/api/client";

/** 400 응답 detail 중 `{missingFields}`(필수 항목 누락)와 `{reason}`(자동 필터 거부)를 구분한다
 * (techspec-backend-content.md §1.2/§1.3) — 전자는 토스트로 안내하고, 후자만 이의제기 진입점이
 * 있는 발행 거부 상태로 보여준다. 두 셸이 글자 단위로 같은 판별을 들고 있던 것을 모았다
 * (fe-convention-refactor-goal-prompt.md R-3). */
export function getFilterRejectionReason(error: unknown): string | undefined {
  const apiError = isApiError(error) ? error : null;
  if (apiError?.status !== 400 || !apiError.detail || typeof apiError.detail !== "object") return undefined;
  if ("reason" in apiError.detail) return String(apiError.detail.reason);
  return undefined;
}

/** 서버 필드명 원문(예: `"thumbnailAssetId"`)을 돌려준다 — 토스트용 한국어 라벨(`MISSING_FIELD_LABELS`)
 * 과 `form.setError()`용 폼 경로(`MISSING_FIELD_FORM_PATH`) 둘 다 이 원문을 키로 찾는다. 그 두 맵은
 * 셸마다 필드 집합이 달라 각 셸에 남는다. */
export function getMissingFields(error: unknown): string[] | undefined {
  const apiError = isApiError(error) ? error : null;
  if (apiError?.status !== 400 || !apiError.detail || typeof apiError.detail !== "object") return undefined;
  const fields = apiError.detail.missingFields;
  if (!Array.isArray(fields)) return undefined;
  return fields.map(String);
}
