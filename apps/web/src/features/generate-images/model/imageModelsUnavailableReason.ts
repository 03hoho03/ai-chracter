import type { UnavailableReason } from "../ui/GenerateImagesUnavailableState";

/** 모델 목록 쿼리 상태로 생성 폼 대신 대체 화면을 보일 사유를 정한다. `undefined`면 폼을 그린다
 * (목록을 기다리는 중이면 폼이 로딩 모양으로 선다).
 *
 * 조회 실패는 **오류가 마지막 성공보다 최근인가**(`errorUpdatedAt > dataUpdatedAt`)로 본다. 쿼리의
 * `isError`로 보면 깜빡인다: 목록을 한 번도 받지 못한 쿼리는 새 조회가 시작될 때마다 상태가 `pending`
 * 으로 돌아가는데, 옵션 시트처럼 이 쿼리를 읽는 컴포넌트가 새로 마운트되기만 해도 재조회가 시작돼
 * 재시도가 끝날 때까지(몇 초) 대체 화면이 로딩 폼으로 바뀌었다. 두 시각은 조회 시작·재시도에서는
 * 바뀌지 않고 성공(`dataUpdatedAt`)과 재시도까지 다 실패한 오류(`errorUpdatedAt`)에서만 바뀌므로,
 * 재조회 동안에는 직전 판정이 유지되고 성공하면 바로 폼으로 돌아간다. 성공한 적 없는 쿼리의
 * `dataUpdatedAt`은 0이다.
 *
 * 목록이 있으면 오류가 더 최근이어도(배경 재조회 실패) 화면을 갈아엎지 않고 그 목록으로 판정한다.
 * "사전 헬스체크 + 즉시 실패" 원칙과 모순되지 않는다: 로컬 비가동은 *성공한* 조회가
 * `available: false`를 실어 오는 값이라 아래 unavailable 분기가 잡는다. 조회 자체의 실패는 "그런지
 * 아닌지도 모른다"이고, 그건 보여줄 게 없을 때만 화면을 대체할 가치가 있다. */
export function getImageModelsUnavailableReason({
  models,
  errorUpdatedAt,
  dataUpdatedAt,
}: {
  models: readonly { available: boolean }[] | undefined;
  errorUpdatedAt: number;
  dataUpdatedAt: number;
}): UnavailableReason | undefined {
  if (models === undefined) return errorUpdatedAt > dataUpdatedAt ? "error" : undefined;
  // 빈 목록과 전 모델 일시 불가는 전에는 "활성화된 빈 Select + 낡은 기본값 + 제출 가능"으로 조용히
  // 깨졌다. 둘 다 제출 이전 상태로 이름을 준다.
  if (models.length === 0) return "empty";
  if (!models.some((model) => model.available)) return "unavailable";
  return undefined;
}
