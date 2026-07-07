/**
 * apps/api의 OpenAPI 스펙에서 `pnpm run codegen`으로 생성한 요청/응답 타입 (techspec-overview-backend.md §3).
 * `./generated.ts`는 자동 생성 파일이므로 직접 수정하지 말고, 스펙이 바뀌면 codegen을 다시 실행한다.
 */
export type { components, operations, paths } from "./generated";

/**
 * shared/lib/api/client.ts의 응답 인터셉터가 모든 에러를 이 포맷으로 정규화한다 (techspec-overview.md §6.1).
 * BE가 실패 응답 스킴을 내려주는 게 아니라 FE(axios 인터셉터)가 자체적으로 만들어내는 형태라서
 * OpenAPI 코드젠 대상이 아니다 — 계속 수동으로 관리한다.
 */
export interface ApiError {
  status: number;
  code: string;
  message: string;
  fields?: Record<string, string>;
}
