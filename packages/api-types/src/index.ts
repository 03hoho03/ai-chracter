/**
 * apps/api의 OpenAPI 스펙에서 `pnpm run codegen`으로 생성한 요청/응답 타입 (techspec-overview-backend.md §3).
 * `./generated.ts`는 자동 생성 파일이므로 직접 수정하지 말고, 스펙이 바뀌면 codegen을 다시 실행한다.
 */
export type { components, operations, paths } from "./generated";

/**
 * shared/lib/api/client.ts의 응답 인터셉터가 모든 에러를 이 포맷으로 정규화한다 (techspec-overview.md §6.1).
 * FastAPI의 실제 에러 바디(`{"detail": ...}`, HTTPException은 string, 422는 배열, 일부는
 * 구조화된 dict — 예: 429 응답의 `{"retryAfterSeconds": n}`)를 그대로 반영한다.
 * OpenAPI 코드젠 대상이 아니다 — 계속 수동으로 관리한다.
 */
export interface ApiError {
  status: number;
  /** HTTPException(status_code, detail=...)의 detail이 string이면 그대로, dict(예: retryAfterSeconds)면 그 객체, 없으면 undefined. */
  detail: string | Record<string, unknown> | undefined;
  /** 422 검증 에러(`[{loc, msg, type}]`)를 필드명 -> 메시지로 펼친 것. 422가 아니면 없음. */
  fields?: Record<string, string>;
  /** 사람이 읽을 수 있는 기본 메시지: detail이 string이면 그 값, 아니면 axios의 원본 메시지로 폴백. */
  message: string;
}
