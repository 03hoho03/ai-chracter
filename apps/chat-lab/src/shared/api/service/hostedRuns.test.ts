import { QueryObserver } from "@tanstack/react-query";
import { AxiosError, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "../queryClient";
import { runKeys } from "../runKeys";
import { describeHostedFailure, HostedError } from "./hostedFailure";
import {
  CONTRACT_VERSION,
  hostedRunKeys,
  hostedRunsQuery,
  loadHostedBundle,
  reloadHostedRuns,
  splitHostedRuns,
} from "./hostedRuns";
import { serviceClient, type HostedRunList, type HostedVersion } from "./serviceClient";

type HostedRunItem = HostedRunList["items"][number];

const RUN_A = "cnVucy9hL2NoYXQuanNvbmw";
const RUN_B = "cnVucy9iL2NoYXQuanNvbmw";
const SHA_A = "a".repeat(64);
const SHA_A2 = "c".repeat(64);
const SHA_B = "b".repeat(64);

/** 측정 서버 목록 한 줄(필수 칸 + 표가 쓰는 칸 몇). 서비스는 올릴 때 받은 이 줄을 그대로 저장한다. */
function runListItem(runId: string, overrides: Record<string, unknown> = {}) {
  return {
    runId,
    path: `2026-11-05/${runId}/chat.jsonl`,
    group: null,
    format: "current",
    supported: true,
    roomId: "room",
    storyName: "지어낸 이야기",
    turnCount: 2,
    costUsd: 0.412,
    hasSnapshots: true,
    hasDump: true,
    hasChatTurns: true,
    ...overrides,
  };
}

function version(sha256: string, overrides: Partial<HostedVersion> = {}): HostedVersion {
  return {
    sha256,
    versionNumber: 3,
    uploadedAt: "2026-11-05T05:02:00Z",
    uploadedBy: "test-client.access",
    raw: false,
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
    ...overrides,
  };
}

function hostedItem(
  runId: string,
  sha256: string,
  options: { latest?: Partial<HostedVersion>; versionCount?: number; run?: Record<string, unknown> } = {},
): HostedRunItem {
  return {
    runId,
    latest: version(sha256, options.latest),
    versionCount: options.versionCount ?? 2,
    run: options.run ?? runListItem(runId),
  };
}

/** 측정 서버 통째 응답 꼴(정적 모드 시험과 같은 꼴). 로더는 겉모양·계약 판·런 id 만 본다. */
function bundleOf(runId: string, overrides: Record<string, unknown> = {}) {
  return {
    contractVersion: CONTRACT_VERSION,
    raw: false,
    detail: { run: runListItem(runId), turns: [] },
    metrics: { turns: [] },
    turns: [{ turn: 1, attempts: [] }],
    ...overrides,
  };
}

type Reply = { status: number; data?: unknown };

/** 서비스 흉내: 목록 응답과 (런 id·sha → 묶음 응답) 표. 표에 없는 묶음은 서비스처럼 404. */
type FakeService = { list: Reply; bundles: Map<string, Reply> };

const BUNDLE_PATH = /^\/api\/runs\/([^/]+)\/versions\/([^/]+)\/bundle$/;

let service: FakeService;
const requests: InternalAxiosRequestConfig[] = [];
const originalAdapter = serviceClient.defaults.adapter;

function serve(items: unknown, bundles: Record<string, unknown> = {}): FakeService {
  return {
    list: { status: 200, data: { items } },
    bundles: new Map(Object.entries(bundles).map(([key, data]) => [key, { status: 200, data }])),
  };
}

function reply(config: InternalAxiosRequestConfig): Reply {
  if (config.method === "get" && config.url === "/api/runs") return service.list;
  const match = BUNDLE_PATH.exec(config.url ?? "");
  const found = match === null ? undefined : service.bundles.get(`${match[1]}/${match[2]}`);
  return found ?? { status: 404, data: { detail: "그런 판이 없다", reason: "notFound" } };
}

const fakeAdapter: AxiosAdapter = (config) => {
  requests.push(config);
  const { status, data } = reply(config);
  const response: AxiosResponse = { data, status, statusText: "", headers: {}, config, request: {} };
  if (status >= 200 && status < 300) return Promise.resolve(response);
  return Promise.reject(new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_REQUEST, config, {}, response));
};

function listRequestCount(): number {
  return requests.filter((config) => config.url === "/api/runs").length;
}

function bundleRequests(): Array<string | undefined> {
  return requests.map((config) => config.url).filter((url) => url?.endsWith("/bundle"));
}

async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("실패해야 할 요청이 성공했다");
}

beforeEach(() => {
  queryClient.clear();
  requests.length = 0;
  service = serve([]);
  serviceClient.defaults.adapter = fakeAdapter;
});

afterEach(() => {
  serviceClient.defaults.adapter = originalAdapter;
  queryClient.clear();
});

describe("splitHostedRuns", () => {
  it("읽을 수 있는 런은 측정 서버 목록 한 줄 그대로 표에 가고, 그 런의 최신 판과 판 수가 따로 붙는다", () => {
    const itemA = hostedItem(RUN_A, SHA_A, { versionCount: 2 });
    const itemB = hostedItem(RUN_B, SHA_B, { versionCount: 1 });

    const { runs, versions, unreadable } = splitHostedRuns([itemA, itemB]);

    expect(runs).toEqual([itemA.run, itemB.run]);
    expect(versions.get(RUN_A)).toEqual({ latest: itemA.latest, versionCount: 2 });
    expect(versions.get(RUN_B)).toEqual({ latest: itemB.latest, versionCount: 1 });
    expect(unreadable).toEqual([]);
  });

  it("측정 서버가 아는 세 형식은 모두 읽는다", () => {
    const items = (["current", "preMessageId", "legacy"] as const).map((format, index) =>
      hostedItem(`run-${index}`, SHA_A, { run: runListItem(`run-${index}`, { format }) }),
    );

    expect(splitHostedRuns(items).runs).toHaveLength(3);
  });

  it("원문 표지는 런마다 그 런의 최신 판으로 고른다 — 표·미리보기·상세 머리가 같은 값을 읽는다", () => {
    const { versions } = splitHostedRuns([
      hostedItem(RUN_A, SHA_A, { latest: { raw: true } }),
      hostedItem(RUN_B, SHA_B, { latest: { raw: false } }),
    ]);

    expect(versions.get(RUN_A)?.latest.raw).toBe(true);
    expect(versions.get(RUN_B)?.latest.raw).toBe(false);
  });

  it("계약 판이 이 웹과 다른 런은 읽지 못하는 런으로 따로 둔다 — 새 판도 옛 판도", () => {
    const newer = hostedItem(RUN_A, SHA_A, { latest: { contractVersion: CONTRACT_VERSION + 1, raw: true }, versionCount: 3 });
    const older = hostedItem(RUN_B, SHA_B, { latest: { contractVersion: 0 } });

    const { runs, unreadable } = splitHostedRuns([newer, older]);

    expect(runs).toEqual([]);
    expect(unreadable).toHaveLength(2);
    // 띠의 행은 계약 판·올린 때·원문 표지를 보이고, 지우기 확인은 판 수를 쓴다.
    expect(unreadable).toContainEqual(
      expect.objectContaining({ runId: RUN_A, reason: "contract", latest: newer.latest, versionCount: 3 }),
    );
    expect(unreadable).toContainEqual(expect.objectContaining({ runId: RUN_B, reason: "contract", latest: older.latest }));
  });

  it("계약 판이 다르면 목록 칸 꼴과 상관없이 계약 판 까닭이다 — 새 계약은 목록 칸 꼴도 바꿀 수 있다", () => {
    const item = hostedItem(RUN_A, SHA_A, { latest: { contractVersion: CONTRACT_VERSION + 1 }, run: { runId: RUN_A } });

    expect(splitHostedRuns([item]).unreadable).toEqual([expect.objectContaining({ runId: RUN_A, reason: "contract" })]);
  });

  it("목록 칸 꼴이 틀리거나 런 id 가 어긋난 런도 읽지 못하는 런이다", () => {
    const broken: Array<[string, Record<string, unknown>]> = [
      ["빈 칸", {}],
      ["경로 없음", { ...runListItem(RUN_A), path: undefined }],
      ["방 id 없음", { ...runListItem(RUN_A), roomId: undefined }],
      ["묶음 무리 칸 없음", { ...runListItem(RUN_A), group: undefined }],
      ["모르는 형식", runListItem(RUN_A, { format: "nextFormat" })],
      ["지원 여부가 불이 아님", runListItem(RUN_A, { supported: "true" })],
      ["런 id 가 글이 아님", runListItem(RUN_A, { runId: 42 })],
      ["목록 칸의 런 id 가 서비스 런 id 와 다름", runListItem(RUN_B)],
    ];

    for (const [label, run] of broken) {
      const { runs, unreadable } = splitHostedRuns([hostedItem(RUN_A, SHA_A, { run })]);

      expect(runs, label).toEqual([]);
      expect(unreadable, label).toEqual([expect.objectContaining({ runId: RUN_A, reason: "shape" })]);
    }
  });

  it("읽지 못한 런도 숨기지 않는다 — 들어온 런은 표나 읽지 못하는 런 띠 어느 한쪽에 꼭 한 번 놓인다", () => {
    const items = [
      hostedItem("readable-1", SHA_A),
      hostedItem("contract", SHA_A, { latest: { contractVersion: CONTRACT_VERSION + 1 } }),
      hostedItem("shape", SHA_A, { run: {} }),
      hostedItem("readable-2", SHA_B),
    ];

    const { runs, unreadable } = splitHostedRuns(items);
    const placed = [...runs.map((run) => run.runId), ...unreadable.map((run) => run.runId)].sort();

    expect(placed).toEqual(["contract", "readable-1", "readable-2", "shape"]);
  });
});

describe("hostedRunsQuery", () => {
  it("목록은 처음 받기·다시 받기·지우기로만 바뀐다 — 오래돼도·포커스·재연결에도 저절로 다시 받지 않는다", () => {
    expect(hostedRunsQuery()).toMatchObject({
      queryKey: hostedRunKeys.list(),
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      retry: false,
    });
  });
});

describe("loadHostedBundle", () => {
  it("목록에 있는 런은 그 런의 최신 판 묶음을 받는다", async () => {
    service = serve([hostedItem(RUN_A, SHA_A)], { [`${RUN_A}/${SHA_A}`]: bundleOf(RUN_A) });

    await expect(loadHostedBundle(RUN_A)).resolves.toEqual(bundleOf(RUN_A));
    expect(bundleRequests()).toEqual([`/api/runs/${RUN_A}/versions/${SHA_A}/bundle`]);
  });

  it("목록에 없는 런의 묶음을 찾으면 찾지 못함이다 — 묶음은 받지 않는다", async () => {
    service = serve([hostedItem(RUN_B, SHA_B)]);

    const error = await rejection(loadHostedBundle(RUN_A));

    expect(error).toBeInstanceOf(HostedError);
    expect(describeHostedFailure(error, "bundle")).toEqual({ kind: "notFound" });
    expect(bundleRequests()).toEqual([]);
  });

  it("목록의 계약 판이 다르면 묶음을 받지 않고 실패한다", async () => {
    const found = CONTRACT_VERSION + 1;
    service = serve([hostedItem(RUN_A, SHA_A, { latest: { contractVersion: found } })], {
      [`${RUN_A}/${SHA_A}`]: bundleOf(RUN_A, { contractVersion: found }),
    });

    const error = await rejection(loadHostedBundle(RUN_A));

    expect(describeHostedFailure(error, "bundle")).toEqual({ kind: "unsupportedContract", found });
    expect(bundleRequests()).toEqual([]);
  });

  it("받은 묶음의 계약 판이 다르면 실패한다 — 목록의 판만 믿지 않는다", async () => {
    const found = CONTRACT_VERSION + 1;
    service = serve([hostedItem(RUN_A, SHA_A)], { [`${RUN_A}/${SHA_A}`]: bundleOf(RUN_A, { contractVersion: found }) });

    const error = await rejection(loadHostedBundle(RUN_A));

    expect(describeHostedFailure(error, "bundle")).toEqual({ kind: "unsupportedContract", found });
  });

  it("받은 묶음의 계약 판이 다르면 묶음 꼴이 틀려도 계약 판 실패다 — 다른 계약은 묶음 꼴도 바꿀 수 있다", async () => {
    const found = CONTRACT_VERSION + 1;
    service = serve([hostedItem(RUN_A, SHA_A)], {
      [`${RUN_A}/${SHA_A}`]: bundleOf(RUN_A, { contractVersion: found, detail: undefined, turns: undefined }),
    });

    const error = await rejection(loadHostedBundle(RUN_A));

    expect(describeHostedFailure(error, "bundle")).toEqual({ kind: "unsupportedContract", found });
  });

  it("받은 묶음이 런 묶음 꼴이 아니거나 다른 런의 묶음이면 응답 꼴 틀림이다", async () => {
    const wrongBodies: Array<[string, unknown]> = [
      ["서비스 거부 본문", { detail: "없다", reason: "notFound" }],
      ["턴 목록 없음", bundleOf(RUN_A, { turns: undefined })],
      ["원문 여부가 불이 아님", bundleOf(RUN_A, { raw: "false" })],
      ["다른 런의 묶음", bundleOf(RUN_B)],
      ["HTML", "<!doctype html><title>로그인</title>"],
    ];

    for (const [label, body] of wrongBodies) {
      queryClient.clear();
      service = serve([hostedItem(RUN_A, SHA_A)], { [`${RUN_A}/${SHA_A}`]: body });

      const error = await rejection(loadHostedBundle(RUN_A));

      expect(describeHostedFailure(error, "bundle"), label).toEqual({ kind: "badResponse" });
    }
  });

  it("목록 응답이 이 웹이 아는 꼴이 아니면 묶음을 받지 않고 응답 꼴 틀림으로 실패한다", async () => {
    for (const body of ["<!doctype html><title>로그인</title>", { runs: [] }, { items: "없음" }, null]) {
      queryClient.clear();
      service = { list: { status: 200, data: body }, bundles: new Map() };

      const error = await rejection(loadHostedBundle(RUN_A));

      expect(describeHostedFailure(error, "bundle"), JSON.stringify(body)).toEqual({ kind: "badResponse" });
    }
    expect(bundleRequests()).toEqual([]);
  });

  it("상세에서 목록을 받다가 404 가 나면 허용 밖이다 — 목록 경로의 404 는 어디서 불렀든 허용 목록 밖 신원뿐이다", async () => {
    // 허용 목록 밖 팀원이 받은 상세 링크를 바로 열면, 목록을 받은 적이 없어 로더의 첫 요청(목록)이 404 로 끝난다.
    service = { list: { status: 404, data: { detail: "없다", reason: "notFound" } }, bundles: new Map() };

    const error = await rejection(loadHostedBundle(RUN_A));

    expect(describeHostedFailure(error, "bundle")).toEqual({ kind: "notAllowed" });
    expect(bundleRequests()).toEqual([]);
  });

  it("같은 런을 다시 열면 목록도 묶음도 다시 받지 않는다", async () => {
    service = serve([hostedItem(RUN_A, SHA_A)], { [`${RUN_A}/${SHA_A}`]: bundleOf(RUN_A) });

    await loadHostedBundle(RUN_A);
    await loadHostedBundle(RUN_A);

    expect(listRequestCount()).toBe(1);
    expect(bundleRequests()).toHaveLength(1);
  });

  it("묶음은 sha 로 이름 붙은 내용이라 오래 둬도 낡지도 버려지지도 않는다", async () => {
    service = serve([hostedItem(RUN_A, SHA_A)], { [`${RUN_A}/${SHA_A}`]: bundleOf(RUN_A) });

    await loadHostedBundle(RUN_A);

    const query = queryClient.getQueryCache().find({ queryKey: hostedRunKeys.bundle(RUN_A, SHA_A), exact: true });
    expect(query?.options).toMatchObject({ staleTime: Infinity, gcTime: Infinity });
  });

  it("다른 런의 묶음을 열면 앞 런의 묶음이 캐시에서 빠진다 — 목록은 남는다", async () => {
    service = serve([hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)], {
      [`${RUN_A}/${SHA_A}`]: bundleOf(RUN_A),
      [`${RUN_B}/${SHA_B}`]: bundleOf(RUN_B),
    });

    await loadHostedBundle(RUN_A);
    await loadHostedBundle(RUN_B);

    expect(queryClient.getQueryCache().findAll({ queryKey: hostedRunKeys.bundlesOf(RUN_A) })).toHaveLength(0);
    expect(queryClient.getQueryData(hostedRunKeys.bundle(RUN_B, SHA_B))).toEqual(bundleOf(RUN_B));
    expect(queryClient.getQueryData(hostedRunKeys.list())).toBeDefined();
    expect(listRequestCount()).toBe(1);
  });
});

describe("reloadHostedRuns", () => {
  it("다시 받기는 런 캐시를 비우고 목록을 새로 받는다 — 그 뒤 런을 열면 새 최신 판 묶음을 받는다", async () => {
    service = serve([hostedItem(RUN_A, SHA_A)], { [`${RUN_A}/${SHA_A}`]: bundleOf(RUN_A) });
    await loadHostedBundle(RUN_A);
    // 옛 판에서 나온 상세·턴·지표 캐시.
    queryClient.setQueryData(runKeys.detail(RUN_A), bundleOf(RUN_A).detail);
    queryClient.setQueryData(runKeys.turn(RUN_A, 1), { turn: 1, attempts: [] });
    queryClient.setQueryData(runKeys.metrics(RUN_A), bundleOf(RUN_A).metrics);
    // 목록 화면이 목록을 보고 있다.
    const observer = new QueryObserver(queryClient, hostedRunsQuery());
    const unsubscribe = observer.subscribe(() => undefined);

    try {
      const renewed = hostedItem(RUN_A, SHA_A2, { latest: { versionNumber: 4 } });
      service = serve([renewed], { [`${RUN_A}/${SHA_A2}`]: bundleOf(RUN_A) });

      await reloadHostedRuns(queryClient);
      await vi.waitFor(() => expect(observer.getCurrentResult().data).toEqual({ items: [renewed] }));

      expect(listRequestCount()).toBe(2);
      expect(queryClient.getQueryCache().findAll({ queryKey: runKeys.all })).toHaveLength(0);
      expect(queryClient.getQueryCache().findAll({ queryKey: hostedRunKeys.bundles() })).toHaveLength(0);

      await loadHostedBundle(RUN_A);
      expect(bundleRequests()).toEqual([
        `/api/runs/${RUN_A}/versions/${SHA_A}/bundle`,
        `/api/runs/${RUN_A}/versions/${SHA_A2}/bundle`,
      ]);
    } finally {
      unsubscribe();
    }
  });
});
