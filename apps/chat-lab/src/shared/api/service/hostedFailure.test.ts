import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import type { components } from "./generated";
import { describeHostedFailure, HostedError } from "./hostedFailure";

type ServiceErrorReason = components["schemas"]["ServiceError"]["reason"];

const WHERES = ["list", "bundle", "delete"] as const;

/**
 * 401·404 밖의 서비스 거부 종류 전부와 서비스가 그 거부에 붙이는 상태 코드 — `Record` 라 서비스가 종류를 늘리고 코드젠을 다시
 * 돌리면 여기서 컴파일이 막힌다. 401(`unauthenticated`)·404(`notFound`)는 상태 코드로 갈래가 정해져 본문을 보지 않는다.
 */
const SERVICE_REFUSAL_STATUSES = {
  tooLarge: 413,
  notGzip: 422,
  notJsonObject: 422,
  noUploadHeader: 422,
  badUploadHeader: 422,
  provenanceFailed: 422,
  noContractVersion: 422,
  unsupportedContract: 422,
  legacyFormat: 422,
  badBundle: 422,
  runIdMismatch: 422,
  badDeleteBody: 422,
  keysUnavailable: 503,
  dbUnavailable: 503,
  internal: 500,
} satisfies Record<Exclude<ServiceErrorReason, "unauthenticated" | "notFound">, number>;

/** 서비스가 2xx 가 아닌 응답을 줬을 때 axios 가 reject 하는 오류와 같은 꼴. */
function rejectedWith(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_REQUEST, config, {}, {
    data,
    status,
    statusText: "",
    headers: {},
    config,
  });
}

describe("describeHostedFailure", () => {
  it("응답 없이 끝난 요청은 세션 끝남으로 본다 — 다른 출처 로그인 화면으로 넘겨진 요청과 네트워크 끊김이 같은 모양이다", () => {
    const config = { headers: new AxiosHeaders() };
    const noResponses = [
      // 브라우저 XHR 이 다른 출처로 넘겨지거나 끊겼을 때.
      new AxiosError("Network Error", AxiosError.ERR_NETWORK, config, {}),
      // fetch 의 네트워크 TypeError 를 axios 가 감싼 것.
      AxiosError.from(new TypeError("Failed to fetch"), AxiosError.ERR_NETWORK, config, {}),
    ];

    for (const error of noResponses) {
      for (const where of WHERES) {
        const outcome = describeHostedFailure(error, where);

        expect(outcome, where).toMatchObject({ kind: "session", code: "응답 없음" });
        expect(outcome, where).not.toMatchObject({ accessBlocked: true });
      }
    }
  });

  it("401 은 세션 끝남이다 — 서비스의 unauthenticated 본문이어도 서비스 오류로 보이지 않는다", () => {
    for (const where of WHERES) {
      const outcome = describeHostedFailure(rejectedWith(401, { detail: "로그인이 필요하다", reason: "unauthenticated" }), where);

      expect(outcome, where).toMatchObject({ kind: "session", code: "401" });
      expect(outcome, where).not.toMatchObject({ accessBlocked: true });
    }
  });

  it("403 은 세션 끝남이고 Access 가 막았다는 표지를 단다 — 서비스는 403 을 쓰지 않는다", () => {
    for (const where of WHERES) {
      const outcome = describeHostedFailure(rejectedWith(403, "<!doctype html><title>Forbidden</title>"), where);

      expect(outcome, where).toMatchObject({ kind: "session", code: "403", accessBlocked: true });
    }
  });

  it("목록의 404 는 허용 밖이다 — 목록 경로는 늘 있어 404 는 허용 목록 밖 신원뿐이다", () => {
    const outcome = describeHostedFailure(rejectedWith(404, { detail: "없다", reason: "notFound" }), "list");

    expect(outcome).toEqual({ kind: "notAllowed" });
  });

  it("묶음·지우기의 404 는 없음이다 — 지워졌거나 옛 주소다", () => {
    const notFound = rejectedWith(404, { detail: "없다", reason: "notFound" });

    expect(describeHostedFailure(notFound, "bundle")).toEqual({ kind: "notFound" });
    expect(describeHostedFailure(notFound, "delete")).toEqual({ kind: "notFound" });
  });

  it("서비스 오류 본문은 detail 과 reason 을 그대로 싣는다", () => {
    for (const [reason, status] of Object.entries(SERVICE_REFUSAL_STATUSES)) {
      const detail = `서비스가 거부했다(${reason})`;

      expect(describeHostedFailure(rejectedWith(status, { detail, reason }), "list"), reason).toEqual({
        kind: "service",
        reason,
        detail,
      });
    }
  });

  it("모르는 reason·꼴 틀린 본문은 응답 꼴 틀림이다 — 웹과 서비스가 다른 커밋에서 나왔을 때다", () => {
    const wrongBodies: Array<[string, number, unknown]> = [
      ["생성 타입에 없는 reason", 422, { detail: "새 종류", reason: "somethingNew" }],
      ["reason 없는 요청 검증 오류", 422, { detail: [{ loc: ["body", "runId"], msg: "Field required", type: "missing" }] }],
      ["detail 이 글이 아님", 422, { detail: { message: "본문이 틀렸다" }, reason: "badDeleteBody" }],
    ];

    for (const [label, status, body] of wrongBodies) {
      expect(describeHostedFailure(rejectedWith(status, body), "list"), label).toEqual({ kind: "badResponse" });
    }
  });

  it("서비스 오류 꼴이 아닌 5xx 는 서비스가 지금 응답하지 않는 것이다 — VM·Tunnel 이 내려가면 앞단이 HTML 오류 화면을 준다", () => {
    const cloudflareErrors: Array<[number, unknown]> = [
      [502, "<!doctype html><title>502 Bad Gateway</title>"],
      [521, "<!doctype html><title>Web server is down</title>"],
      [530, "<!doctype html><title>Origin DNS error</title>"],
      [504, undefined],
    ];

    for (const [status, body] of cloudflareErrors) {
      for (const where of WHERES) {
        expect(describeHostedFailure(rejectedWith(status, body), where), `${status} · ${where}`).toEqual({
          kind: "unavailable",
          status,
        });
      }
    }
  });

  it("서비스 오류 꼴인 503 은 응답하지 않음이 아니라 서비스 오류다 — 서비스가 까닭을 말한 것이다", () => {
    const detail = "DB 를 쓰지 못했다: OperationalError";

    for (const where of WHERES) {
      expect(describeHostedFailure(rejectedWith(503, { detail, reason: "dbUnavailable" }), where), where).toEqual({
        kind: "service",
        reason: "dbUnavailable",
        detail,
      });
    }
  });

  it("서비스 오류 꼴이 아닌 4xx 는 응답하지 않음이 아니라 응답 꼴 틀림이다", () => {
    for (const where of WHERES) {
      expect(describeHostedFailure(rejectedWith(400, "<!doctype html><title>400 Bad Request</title>"), where), where).toEqual({
        kind: "badResponse",
      });
    }
  });

  it("axios 오류가 아닌 예외는 세션 끝남으로 보지 않는다 — 응답 꼴 틀림이다", () => {
    expect(describeHostedFailure(new TypeError("items.find is not a function"), "list")).toEqual({ kind: "badResponse" });
  });

  it("로더가 던진 호스팅 오류는 그 reason 그대로다 — 어디서 불렀는지와 상관없다", () => {
    expect(describeHostedFailure(new HostedError("notFound"), "list")).toEqual({ kind: "notFound" });
    expect(describeHostedFailure(new HostedError("badResponse"), "bundle")).toEqual({ kind: "badResponse" });
  });
});
