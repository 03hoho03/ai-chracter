/**
 * 수동 작성 API 요청/응답 타입 (techspec-overview.md §6.2).
 * BE의 OpenAPI 스펙이 확정되면 코드젠 결과물로 교체될 예정이므로,
 * 여기에는 실제 엔드포인트가 생기기 전까지 공용 타입만 최소로 둔다.
 */

/** shared/lib/api/client.ts의 응답 인터셉터가 모든 에러를 이 포맷으로 정규화한다 (techspec-overview.md §6.1). */
export interface ApiError {
  status: number;
  code: string;
  message: string;
  fields?: Record<string, string>;
}
