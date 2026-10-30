import { isAxiosError } from "axios";

import type { components } from "./generated";

type LabError = components["schemas"]["LabError"];
type LabErrorReason = LabError["reason"];

/**
 * 생성 타입의 `reason` 유니온을 실행 중에 대조할 목록. 키가 하나라도 빠지면 `Record` 가, 유니온에 없는 키가 있으면 객체
 * 리터럴의 초과 속성 검사가 컴파일을 막는다 — 서버가 종류를 바꾸고 codegen 을 다시 돌리면 여기를 고칠 때까지 typecheck 가
 * 실패한다.
 */
const LAB_ERROR_REASONS = {
  notFound: true,
  unsupported: true,
  openFailed: true,
  archived: true,
  exists: true,
  notFile: true,
  noRoom: true,
  noRows: true,
  multipleRooms: true,
  dbUnavailable: true,
  notJson: true,
} as const satisfies Record<LabErrorReason, true>;

/**
 * 측정 서버가 요청을 거부하며 보낸 오류 본문. 화면은 `reason` 으로 갈래를 고르고 `detail` 을 사람에게 보여 준다.
 *
 * `undefined` 인 경우: axios 오류가 아니거나, 응답이 없거나(서버가 꺼졌거나 CORS 로 막힘), 본문이 이 모양이 아니다. 마지막은
 * FastAPI 의 요청 검증 오류(422)가 `reason` 없이 `detail` 을 목록으로 보내는 경우, 그리고 이 앱보다 새 서버가 생성 타입에
 * 없는 `reason` 을 보낸 경우다.
 */
export function readLabError(error: unknown): LabError | undefined {
  if (!isAxiosError<unknown>(error)) return undefined;
  const body = error.response?.data;
  return isLabError(body) ? body : undefined;
}

function isLabError(body: unknown): body is LabError {
  return (
    typeof body === "object" &&
    body !== null &&
    "detail" in body &&
    typeof body.detail === "string" &&
    "reason" in body &&
    isLabErrorReason(body.reason)
  );
}

function isLabErrorReason(value: unknown): value is LabErrorReason {
  return typeof value === "string" && Object.hasOwn(LAB_ERROR_REASONS, value);
}
