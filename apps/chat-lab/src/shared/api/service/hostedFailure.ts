import { isAxiosError } from "axios";

import { assertNever } from "@/shared/lib/assertNever";
import { isRecord } from "@/shared/lib/isRecord";

import type { components } from "./generated";

type ServiceError = components["schemas"]["ServiceError"];
type ServiceErrorReason = ServiceError["reason"];

/**
 * 생성 타입의 `reason` 유니온을 실행 중에 대조할 목록. 키가 빠지면 `Record` 가, 유니온에 없는 키가 있으면 객체 리터럴의 초과 속성
 * 검사가 컴파일을 막는다 — 서비스가 종류를 바꾸고 코드젠을 다시 돌리면 여기를 고칠 때까지 typecheck 가 실패한다.
 */
const SERVICE_ERROR_REASONS = {
  unauthenticated: true,
  notFound: true,
  tooLarge: true,
  notGzip: true,
  notJsonObject: true,
  noUploadHeader: true,
  badUploadHeader: true,
  provenanceFailed: true,
  noContractVersion: true,
  unsupportedContract: true,
  legacyFormat: true,
  badBundle: true,
  runIdMismatch: true,
  badDeleteBody: true,
  keysUnavailable: true,
  dbUnavailable: true,
  internal: true,
} as const satisfies Record<ServiceErrorReason, true>;

/** 어디서 부른 요청인가. 같은 404 라도 목록에서는 허용 밖 신원, 묶음·지우기에서는 없는 런이다. */
export type HostedRequestSite = "list" | "bundle" | "delete";

/**
 * 호스팅 화면이 서비스에서 런을 내지 못한 까닭. 화면은 이 갈래로 안내 문장을 고른다.
 * - `session`: 응답이 없거나(Access 세션이 끝나 다른 출처 로그인 화면으로 넘겨진 요청과 네트워크 끊김이 같은 모양이다) 401·403.
 *   서비스는 403 을 쓰지 않아, 403 은 Access 가 막은 것이다(`accessBlocked`).
 * - `notAllowed`: 목록 경로의 404 — 목록 경로는 늘 있으므로 허용 목록 밖 신원뿐이다.
 * - `notFound`: 묶음·지우기의 404, 또는 목록에 없는 런 — 지워졌거나 옛 주소다.
 * - `service`: 서비스가 까닭을 말한 거부. 문장을 고치지 않고 그대로 보인다.
 * - `unavailable`: 서비스 거부 꼴이 아닌 5xx — 서비스나 그 앞단이 내려가 앞단이 오류 화면을 준 것이다.
 * - `badResponse`: 이 웹이 아는 꼴이 아닌 응답 — 웹과 서비스가 다른 커밋에서 나왔을 때다.
 * - `serverless`: 측정 서버가 있어야 하는 요청 — 호스팅 화면은 측정 서버에 닿지 않는다.
 * - `unsupportedContract`: 이 웹이 읽지 못하는 계약 판의 묶음(`found` 가 그 판).
 */
export type HostedFailure =
  | { kind: "session"; code: "응답 없음" | "401" | "403"; accessBlocked: boolean }
  | { kind: "notAllowed" }
  | { kind: "notFound" }
  | { kind: "service"; reason: ServiceErrorReason; detail: string }
  | { kind: "unavailable"; status: number }
  | { kind: "badResponse" }
  | { kind: "serverless" }
  | { kind: "unsupportedContract"; found: number };

type HostedErrorDetail =
  | { reason: "serverless" | "notFound" | "badResponse" }
  | { reason: "unsupportedContract"; found: number }
  /** 묶음을 받으려고 목록을 먼저 받다가 실패했다. 목록 요청의 실패라 목록 화면과 같은 잣대로 본다(목록의 404 는 허용 밖). */
  | { reason: "listFailed"; listError: unknown };

const HOSTED_ERROR_MESSAGES = {
  serverless: "호스팅 화면은 측정 서버에 닿지 않는다",
  notFound: "서비스 목록에 그 런이 없다",
  badResponse: "서비스 응답이 이 웹이 아는 꼴이 아니다",
  unsupportedContract: "이 웹이 읽지 못하는 계약 판의 묶음이다",
  listFailed: "묶음을 받기 전에 런 목록을 받지 못했다",
} as const satisfies Record<HostedErrorDetail["reason"], string>;

/** 호스팅 갈래의 로더·요청 차단이 던지는 오류. 서비스 응답이 아니라 이 웹이 판정한 실패다. */
export class HostedError extends Error {
  readonly reason: HostedErrorDetail["reason"];
  readonly detail: HostedErrorDetail;

  constructor(detail: HostedErrorDetail | "serverless" | "notFound" | "badResponse") {
    const resolved = typeof detail === "string" ? { reason: detail } : detail;
    super(HOSTED_ERROR_MESSAGES[resolved.reason]);
    this.name = "HostedError";
    this.reason = resolved.reason;
    this.detail = resolved;
  }
}

/** 실패를 화면 갈래로. `site` 는 실패한 요청을 부른 자리다. */
export function describeHostedFailure(error: unknown, site: HostedRequestSite): HostedFailure {
  if (error instanceof HostedError) return describeHostedError(error.detail);
  if (!isAxiosError<unknown>(error)) return { kind: "badResponse" };

  const response = error.response;
  if (response === undefined) return { kind: "session", code: "응답 없음", accessBlocked: false };
  // 상태 코드로 갈래가 정해지는 것을 먼저 본다 — 401 은 서비스의 unauthenticated 본문이어도 세션 끝남이다.
  if (response.status === 401) return { kind: "session", code: "401", accessBlocked: false };
  if (response.status === 403) return { kind: "session", code: "403", accessBlocked: true };
  if (response.status === 404) return site === "list" ? { kind: "notAllowed" } : { kind: "notFound" };

  const body = response.data;
  if (isServiceError(body)) return { kind: "service", reason: body.reason, detail: body.detail };
  if (response.status >= 500) return { kind: "unavailable", status: response.status };
  return { kind: "badResponse" };
}

function describeHostedError(detail: HostedErrorDetail): HostedFailure {
  switch (detail.reason) {
    case "serverless":
    case "notFound":
    case "badResponse":
      return { kind: detail.reason };
    case "unsupportedContract":
      return { kind: "unsupportedContract", found: detail.found };
    case "listFailed":
      return describeHostedFailure(detail.listError, "list");
    default:
      return assertNever(detail);
  }
}

function isServiceError(body: unknown): body is ServiceError {
  return (
    isRecord(body) &&
    typeof body.detail === "string" &&
    typeof body.reason === "string" &&
    Object.hasOwn(SERVICE_ERROR_REASONS, body.reason)
  );
}
