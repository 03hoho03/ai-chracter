import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";

import type { components } from "@/shared/api/generated";

import { describeExportFailure } from "./exportFailure";

type LabErrorReason = components["schemas"]["LabError"]["reason"];

/**
 * 이미 있음 밖의 거부 종류 전부와 측정 서버가 그 거부에 붙이는 상태 코드 — `Record` 라 서버가 종류를 늘리면 여기서 컴파일이
 * 막힌다.
 */
const REFUSAL_STATUSES = {
  notFound: 404,
  unsupported: 422,
  openFailed: 422,
  archived: 403,
  notFile: 422,
  noRoom: 422,
  noRows: 422,
  multipleRooms: 422,
  dbUnavailable: 503,
  notJson: 415,
} satisfies Record<Exclude<LabErrorReason, "exists">, number>;

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

describe("describeExportFailure", () => {
  it("이미 있음(409)이면 덮어쓸지 묻는다 — 서버 문장을 그대로 싣는다", () => {
    const detail = "chat-turns.jsonl 가 이미 있다 — 바꾸려면 강제로 다시 내보낸다";

    expect(describeExportFailure(rejectedWith(409, { detail, reason: "exists" }))).toEqual({
      kind: "confirmOverwrite",
      detail,
    });
  });

  it("방이 DB 에 없으면 서버 문장 그대로에 DB 주소를 가리키라는 안내를 붙인다", () => {
    const detail = "DB 에 방 0000 이 없다 — 이 런을 돈 DB 인지 확인한다";
    const outcome = describeExportFailure(rejectedWith(422, { detail, reason: "noRoom" }));

    expect(outcome).toMatchObject({ kind: "refused", reason: "noRoom", detail });
    if (outcome.kind !== "refused") return;
    expect(outcome.hint).toContain("--database-url");
  });

  it("거부 종류마다 서로 다른 안내가 붙는다", () => {
    const reasons = ["notFile", "noRows", "multipleRooms", "archived", "dbUnavailable", "unsupported"] as const;
    const hints = reasons.map((reason) => {
      const outcome = describeExportFailure(rejectedWith(422, { detail: "거부", reason }));
      return outcome.kind === "refused" ? outcome.hint : undefined;
    });

    expect(hints.every((hint) => typeof hint === "string" && hint.length > 0)).toBe(true);
    expect(new Set(hints).size).toBe(reasons.length);
  });

  it("강제 덮어쓰기는 이미 있음(exists)에만 권한다 — 링크·폴더가 그 자리에 있음(notFile) 같은 다른 거부는 강제로도 못 쓴다", () => {
    for (const [reason, status] of Object.entries(REFUSAL_STATUSES)) {
      const outcome = describeExportFailure(rejectedWith(status, { detail: "거부", reason }));

      expect(outcome.kind, reason).toBe("refused");
    }
    expect(describeExportFailure(rejectedWith(409, { detail: "있다", reason: "exists" })).kind).toBe("confirmOverwrite");
  });

  it("응답 없이 끝났으면(서버가 꺼짐) 서버에 닿지 못한 것으로", () => {
    expect(describeExportFailure(new AxiosError("Network Error", AxiosError.ERR_NETWORK))).toEqual({
      kind: "unreachable",
    });
  });

  it("측정 서버의 거부 본문이 아니면 오류 글을 그대로", () => {
    const outcome = describeExportFailure(rejectedWith(422, { detail: [{ msg: "Field required" }] }));

    expect(outcome).toEqual({ kind: "unknown", message: "Request failed with status code 422" });
  });
});
