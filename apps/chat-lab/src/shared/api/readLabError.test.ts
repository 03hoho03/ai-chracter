import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { readLabError } from "./readLabError";

/** 서버가 2xx 가 아닌 응답을 줬을 때 axios 가 reject 하는 오류와 같은 꼴. */
function rejectedWith(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_REQUEST, config, undefined, {
    data,
    status,
    statusText: "",
    headers: {},
    config,
  });
}

describe("readLabError", () => {
  it("측정 서버의 거부 본문이면 detail 과 reason 을 그대로 돌려준다", () => {
    const body = { detail: "턴 기록 파일이 이미 있다", reason: "exists" };

    expect(readLabError(rejectedWith(409, body))).toEqual(body);
  });

  it("FastAPI 요청 검증 오류처럼 reason 없이 detail 이 목록이면 undefined", () => {
    const body = { detail: [{ loc: ["path", "clientTurn"], msg: "Input should be a valid integer", type: "int_parsing" }] };

    expect(readLabError(rejectedWith(422, body))).toBeUndefined();
  });

  it("생성 타입에 없는 reason 이면 undefined", () => {
    expect(readLabError(rejectedWith(409, { detail: "새 종류", reason: "somethingNew" }))).toBeUndefined();
  });

  it("detail 이 글이 아니면 reason 이 맞아도 undefined", () => {
    expect(readLabError(rejectedWith(404, { detail: { message: "없다" }, reason: "notFound" }))).toBeUndefined();
  });

  it("응답 없이 끝난 요청(서버가 꺼졌거나 CORS 로 막힘)이면 undefined", () => {
    expect(readLabError(new AxiosError("Network Error", AxiosError.ERR_NETWORK))).toBeUndefined();
  });

  it("axios 오류가 아니면 같은 모양의 응답을 달고 있어도 undefined", () => {
    const lookalike = { response: { data: { detail: "없다", reason: "notFound" } } };

    expect(readLabError(lookalike)).toBeUndefined();
    expect(readLabError(new Error("없다"))).toBeUndefined();
  });
});
