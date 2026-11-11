import { QueryClient } from "@tanstack/react-query";
import { AxiosError, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { runKeys } from "@/shared/api/runKeys";
import { describeHostedFailure } from "@/shared/api/service/hostedFailure";
import { CONTRACT_VERSION, hostedRunKeys } from "@/shared/api/service/hostedRuns";
import { serviceClient } from "@/shared/api/service/serviceClient";

import { versionsChangedText } from "../model/deleteCopy";
import { deleteRunIfUnchanged } from "./deleteRunIfUnchanged";

const RUN_A = "cnVucy9hL2NoYXQuanNvbmw";
const RUN_B = "cnVucy9iL2NoYXQuanNvbmw";
const SHA_A = "a".repeat(64);
const SHA_A2 = "c".repeat(64);
const SHA_B = "b".repeat(64);
const SHA_B2 = "d".repeat(64);

function hostedItem(runId: string, sha256: string, options: { versionCount?: number; raw?: boolean } = {}) {
  return {
    runId,
    versionCount: options.versionCount ?? 1,
    latest: {
      sha256,
      versionNumber: options.versionCount ?? 1,
      uploadedAt: "2026-11-05T05:02:00Z",
      uploadedBy: "test-client.access",
      raw: options.raw ?? false,
      contractVersion: CONTRACT_VERSION,
      sourceCommit: { commit: "0".repeat(40), dirty: false },
      provenance: {
        passed: true,
        baseLocal: true,
        roomFound: true,
        ownerInExampleDomain: true,
        outsideUsers: 0,
        exemptedUsers: 0,
        authorInExampleDomain: true,
      },
      compressedSize: 1024,
      uncompressedSize: 4096,
    },
    run: { runId, path: `${runId}/chat.jsonl`, group: null, format: "current", supported: true, roomId: "room" },
  };
}

type Reply = { status: number; data?: unknown };

/** 서비스가 지금 가진 목록. 지우기 요청은 그 런의 판 수를 지운 판 수로 돌려준다. */
let serviceList: Reply;
const requests: InternalAxiosRequestConfig[] = [];
const originalAdapter = serviceClient.defaults.adapter;

const fakeAdapter: AxiosAdapter = (config) => {
  requests.push(config);
  const { status, data } =
    config.method === "get" && config.url === "/api/runs"
      ? serviceList
      : { status: 200, data: { runId: decodeURIComponent(config.url?.split("/").at(-1) ?? ""), deletedVersions: 2 } };
  const response: AxiosResponse = { data, status, statusText: "", headers: {}, config, request: {} };
  if (status >= 200 && status < 300) return Promise.resolve(response);
  return Promise.reject(new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_REQUEST, config, {}, response));
};

function deleteRequests(): InternalAxiosRequestConfig[] {
  return requests.filter((config) => config.method === "delete");
}

function listRequests(): InternalAxiosRequestConfig[] {
  return requests.filter((config) => config.method === "get" && config.url === "/api/runs");
}

/** 대화를 연 때의 목록 캐시 — 런 A 는 판 1개, 원문 제외. 런 A·B 의 묶음·상세를 한 번씩 열어 봤다. */
function openedClient(): QueryClient {
  const queryClient = new QueryClient();
  queryClient.setQueryData(hostedRunKeys.list(), { items: [hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)] });
  for (const [runId, sha256] of [
    [RUN_A, SHA_A],
    [RUN_B, SHA_B],
  ] as const) {
    queryClient.setQueryData(hostedRunKeys.bundle(runId, sha256), { contractVersion: CONTRACT_VERSION, runId });
    queryClient.setQueryData(runKeys.detail(runId), { runId });
  }
  return queryClient;
}

const SEEN_A = { sha256: SHA_A, versionCount: 1, raw: false };

async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("실패해야 할 요청이 성공했다");
}

beforeEach(() => {
  requests.length = 0;
  serviceClient.defaults.adapter = fakeAdapter;
});

afterEach(() => {
  serviceClient.defaults.adapter = originalAdapter;
});

describe("deleteRunIfUnchanged", () => {
  it("캐시는 판 1개인데 지우기 직전에 새로 받은 목록이 판 2개면 지우지 않고 목록 캐시를 새 목록으로 바꾼다 — 대화는 새 판 수로 다시 그려진다", async () => {
    const queryClient = openedClient();
    const fresh = { items: [hostedItem(RUN_A, SHA_A2, { versionCount: 2, raw: true }), hostedItem(RUN_B, SHA_B)] };
    serviceList = { status: 200, data: fresh };

    const attempt = await deleteRunIfUnchanged(queryClient, RUN_A, SEEN_A);

    expect(attempt).toEqual({ kind: "changed", versionCount: 2 });
    expect(deleteRequests()).toHaveLength(0);
    expect(queryClient.getQueryData(hostedRunKeys.list())).toEqual(fresh);
    expect(versionsChangedText(2)).toBe("그 사이 새 판이 올라왔다 — 목록을 다시 받았다. 판 2개를 다시 보고 지운다.");
  });

  it("목록 캐시에 판이 이미 있어도 지우기 직전에는 목록을 캐시를 거치지 않고 새로 받는다", async () => {
    const queryClient = openedClient();
    serviceList = { status: 200, data: { items: [hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)] } };

    await deleteRunIfUnchanged(queryClient, RUN_A, SEEN_A);

    expect(listRequests()).toHaveLength(1);
  });

  it("판 수가 같아도 최신 판 sha256 이나 원문 여부가 다르면 지우지 않는다", async () => {
    const changes = [
      ["최신 판이 다른 판", hostedItem(RUN_A, SHA_A2)],
      ["원문 여부가 다름", hostedItem(RUN_A, SHA_A, { raw: true })],
    ] as const;

    for (const [label, item] of changes) {
      requests.length = 0;
      serviceList = { status: 200, data: { items: [item, hostedItem(RUN_B, SHA_B)] } };

      const attempt = await deleteRunIfUnchanged(openedClient(), RUN_A, SEEN_A);

      expect(attempt, label).toEqual({ kind: "changed", versionCount: 1 });
      expect(deleteRequests(), label).toHaveLength(0);
    }
  });

  it("sha256·원문 여부가 같아도 판 수가 다르면 지우지 않는다 — 지운 옛 판이 되살아나면 최신 판은 그대로인 채 판 수만 는다", async () => {
    const queryClient = openedClient();
    // 서비스는 지운 판을 되살릴 때 옛 번호를 쓰고 최신 판은 살아 있는 판 가운데 번호가 가장 큰 것이라, 대화를 연 뒤 누가 더 옛
    // 판(원문 포함일 수 있다)을 다시 올리면 최신 판은 그대로이고 살아 있는 판 수만 는다.
    const revived = { ...hostedItem(RUN_A, SHA_A), versionCount: 2 };
    serviceList = { status: 200, data: { items: [revived, hostedItem(RUN_B, SHA_B)] } };

    const attempt = await deleteRunIfUnchanged(queryClient, RUN_A, SEEN_A);

    expect(attempt).toEqual({ kind: "changed", versionCount: 2 });
    expect(deleteRequests()).toHaveLength(0);
    expect(queryClient.getQueryData(hostedRunKeys.list())).toEqual({ items: [revived, hostedItem(RUN_B, SHA_B)] });
  });

  it("새로 받은 목록이 대화를 연 때와 같으면 지우기를 한 번 보낸다 — 목록을 받은 뒤에", async () => {
    const queryClient = openedClient();
    serviceList = { status: 200, data: { items: [hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)] } };

    const attempt = await deleteRunIfUnchanged(queryClient, RUN_A, SEEN_A);

    expect(attempt).toEqual({ kind: "deleted", deletedVersions: 2 });
    expect(requests.map((config) => `${config.method ?? ""} ${config.url ?? ""}`)).toEqual([
      "get /api/runs",
      `delete /api/runs/${RUN_A}`,
    ]);
  });

  it("새로 받은 목록에 그 런이 없으면 지우지 않고 이미 지워진 런이다", async () => {
    serviceList = { status: 200, data: { items: [hostedItem(RUN_B, SHA_B)] } };

    const attempt = await deleteRunIfUnchanged(openedClient(), RUN_A, SEEN_A);

    expect(attempt).toEqual({ kind: "alreadyDeleted" });
    expect(deleteRequests()).toHaveLength(0);
  });

  it("목록을 새로 받지 못하면 지우지 않는다 — 목록의 404 는 지워진 런이 아니라 허용 밖이다", async () => {
    const queryClient = openedClient();
    serviceList = { status: 404, data: { detail: "없다", reason: "notFound" } };

    const error = await rejection(deleteRunIfUnchanged(queryClient, RUN_A, SEEN_A));

    expect(describeHostedFailure(error, "delete")).toEqual({ kind: "notAllowed" });
    expect(deleteRequests()).toHaveLength(0);
    expect(queryClient.getQueryData(hostedRunKeys.list())).toEqual({
      items: [hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)],
    });
  });

  it("목록 캐시에서는 그 런만 새 값으로 바꾸고 다른 런은 대화를 연 때 그대로 둔다 — 다른 런의 최신 판이 바뀌어 열어 둔 옛 판과 섞이거나 표의 행이 바뀌지 않게", async () => {
    const queryClient = openedClient();
    const receivedAt = queryClient.getQueryState(hostedRunKeys.list())?.dataUpdatedAt;
    serviceList = {
      status: 200,
      data: {
        items: [hostedItem("new-run", SHA_B2), hostedItem(RUN_A, SHA_A2, { versionCount: 2 }), hostedItem(RUN_B, SHA_B2)],
      },
    };

    await deleteRunIfUnchanged(queryClient, RUN_A, SEEN_A);

    expect(queryClient.getQueryData(hostedRunKeys.list())).toEqual({
      items: [hostedItem(RUN_A, SHA_A2, { versionCount: 2 }), hostedItem(RUN_B, SHA_B)],
    });
    // 다시 받은 것은 그 런 하나라 목록 머리의 받은 때는 그대로다.
    expect(queryClient.getQueryState(hostedRunKeys.list())?.dataUpdatedAt).toBe(receivedAt);
    expect(queryClient.getQueryData(hostedRunKeys.bundle(RUN_B, SHA_B))).toBeDefined();
    expect(queryClient.getQueryData(runKeys.detail(RUN_B))).toBeDefined();
  });

  it("그 런의 최신 판이 바뀌었으면 옛 판의 묶음·상세 캐시를 버린다 — 다음에 열 때 새 판을 받는다", async () => {
    const queryClient = openedClient();
    serviceList = { status: 200, data: { items: [hostedItem(RUN_A, SHA_A2, { versionCount: 2 }), hostedItem(RUN_B, SHA_B)] } };

    await deleteRunIfUnchanged(queryClient, RUN_A, SEEN_A);

    expect(queryClient.getQueryCache().findAll({ queryKey: hostedRunKeys.bundlesOf(RUN_A) })).toHaveLength(0);
    expect(queryClient.getQueryCache().findAll({ queryKey: runKeys.run(RUN_A) })).toHaveLength(0);
  });
});
