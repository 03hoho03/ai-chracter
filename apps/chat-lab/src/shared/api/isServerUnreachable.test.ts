import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import { isServerUnreachable } from "./isServerUnreachable";

describe("isServerUnreachable", () => {
  it("응답 없이 끝난 요청(서버가 꺼졌거나 CORS 로 막힘)이면 참", () => {
    expect(isServerUnreachable(new AxiosError("Network Error", AxiosError.ERR_NETWORK))).toBe(true);
  });

  it("서버가 응답한 실패면 거짓 — 거부 사유를 보여 줄 자리다", () => {
    const config = { headers: new AxiosHeaders() };
    const rejected = new AxiosError("Request failed with status code 422", AxiosError.ERR_BAD_REQUEST, config, undefined, {
      data: { detail: "이 묶음은 열지 않는다", reason: "unsupported" },
      status: 422,
      statusText: "",
      headers: {},
      config,
    });

    expect(isServerUnreachable(rejected)).toBe(false);
  });

  it("axios 오류가 아니면 거짓", () => {
    expect(isServerUnreachable(new Error("Network Error"))).toBe(false);
  });
});
