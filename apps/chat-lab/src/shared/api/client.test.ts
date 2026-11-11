import axios, { AxiosError, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CONTRACT_VERSION } from "./service/hostedRuns";
import { STATIC_BUNDLE_ELEMENT_ID } from "./staticBundleElement";

const RUN_A = "cnVucy9hL2NoYXQuanNvbmw";
const RUN_B = "cnVucy9iL2NoYXQuanNvbmw";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);

type Reply = { status: number; data?: unknown };
type Route = (config: InternalAxiosRequestConfig) => Reply;

/** 요청마다 답을 고르는 가짜 어댑터 — 네트워크에 나가지 않고 받은 요청을 모은다. 2xx 가 아니면 axios 처럼 거절한다. */
function fakeAdapter(route: Route) {
  const requests: InternalAxiosRequestConfig[] = [];
  const adapter: AxiosAdapter = (config) => {
    requests.push(config);
    const reply = route(config);
    const response: AxiosResponse = { data: reply.data, status: reply.status, statusText: "", headers: {}, config, request: {} };
    if (reply.status >= 200 && reply.status < 300) return Promise.resolve(response);
    return Promise.reject(
      new AxiosError(`Request failed with status code ${reply.status}`, AxiosError.ERR_BAD_REQUEST, config, {}, response),
    );
  };
  return { adapter, requests };
}

/** 측정 서버 목록 한 줄 — 서비스 목록의 `run` 칸에 그대로 실린다. */
function runListItem(runId: string) {
  return { runId, path: `${runId}/chat.jsonl`, group: null, format: "current", supported: true, roomId: "room" };
}

function hostedItem(runId: string, sha256: string) {
  return {
    runId,
    versionCount: 1,
    latest: {
      sha256,
      versionNumber: 1,
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
    },
    run: runListItem(runId),
  };
}

/** 측정 서버 통째 응답 꼴(정적 모드 시험과 같은 꼴). 턴 번호와 배열 순번이 다르게 둔다 — 턴은 번호로 찾아야 한다. */
function bundleOf(runId: string) {
  return {
    contractVersion: CONTRACT_VERSION,
    raw: false,
    detail: { run: runListItem(runId), turns: [{ turn: 3 }, { turn: 5 }] },
    metrics: { turns: [{ turn: 3 }, { turn: 5 }], runId },
    turns: [
      { turn: 3, attempts: [] },
      { turn: 5, attempts: [] },
    ],
  };
}

const BUNDLE_PATH = /^\/api\/runs\/([^/]+)\/versions\/([^/]+)\/bundle$/;

/** 목록에 런 A·B 가 있고 각 런의 최신 판 묶음을 주는 서비스. */
const serviceWithTwoRuns: Route = (config) => {
  if (config.method === "get" && config.url === "/api/runs") {
    return { status: 200, data: { items: [hostedItem(RUN_A, SHA_A), hostedItem(RUN_B, SHA_B)] } };
  }
  const match = BUNDLE_PATH.exec(config.url ?? "");
  if (config.method === "get" && match !== null) {
    const [, runId, sha256] = match;
    if (runId === RUN_A && sha256 === SHA_A) return { status: 200, data: bundleOf(RUN_A) };
    if (runId === RUN_B && sha256 === SHA_B) return { status: 200, data: bundleOf(RUN_B) };
  }
  return { status: 404, data: { detail: "없다", reason: "notFound" } };
};

const originalAdapter = axios.defaults.adapter;

/**
 * 빌드 상수·문서를 흉내 내고 모듈을 새로 읽는다. 정적 묶음 상태·쿼리 캐시가 모듈 변수라 시험마다 모듈 기록을 비운다.
 * 측정 서버 인스턴스는 만들어질 때 기본 어댑터를 받으므로 읽기 전에 기본 어댑터를 가짜로 바꾸고, 서비스 인스턴스는 읽은 뒤
 * 자기 어댑터를 따로 바꾼다 — 두 쪽으로 나간 요청을 따로 센다.
 */
async function loadApi(options: { mode: string | undefined; staticBundleText?: string; service?: Route }) {
  vi.stubEnv("VITE_CHAT_LAB_MODE", options.mode);
  vi.stubGlobal("document", {
    getElementById: (id: string) =>
      id === STATIC_BUNDLE_ELEMENT_ID && options.staticBundleText !== undefined
        ? { textContent: options.staticBundleText }
        : null,
  });
  const measurement = fakeAdapter(() => ({ status: 200, data: { measurementServer: true } }));
  axios.defaults.adapter = measurement.adapter;
  vi.resetModules();
  const [client, { serviceClient }, { HostedError, describeHostedFailure }, { StaticBundleError }] = await Promise.all([
    import("./client"),
    import("./service/serviceClient"),
    import("./service/hostedFailure"),
    import("./staticBundle"),
  ]);
  const service = fakeAdapter(options.service ?? serviceWithTwoRuns);
  serviceClient.defaults.adapter = service.adapter;
  return {
    ...client,
    HostedError,
    describeHostedFailure,
    StaticBundleError,
    measurementRequests: measurement.requests,
    serviceRequests: service.requests,
  };
}

/** 실패해야 할 약속이 던진 값. 성공하면 시험이 실패한다. */
async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("실패해야 할 요청이 성공했다");
}

function thrownBy(run: () => void): unknown {
  try {
    run();
  } catch (error) {
    return error;
  }
  return undefined;
}

afterEach(() => {
  axios.defaults.adapter = originalAdapter;
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("refuseServerlessRequest", () => {
  it("호스팅 화면은 측정 서버로 요청을 내지 않고 호스팅 오류로 막는다", async () => {
    const api = await loadApi({ mode: "hosted" });

    const thrown = thrownBy(() => api.refuseServerlessRequest("hosted"));
    expect(thrown).toBeInstanceOf(api.HostedError);
    expect(thrown).toMatchObject({ reason: "serverless" });

    const errors = await Promise.all([
      rejection(api.getRuns()),
      rejection(api.getHealth()),
      rejection(api.getRunBundle(RUN_A, { raw: false })),
      rejection(api.exportTurns(RUN_A, { force: false })),
    ]);
    for (const error of errors) {
      expect(error).toBeInstanceOf(api.HostedError);
      expect(api.describeHostedFailure(error, "list")).toEqual({ kind: "serverless" });
    }
    expect(api.measurementRequests).toHaveLength(0);
  });

  it("정적 화면은 지금처럼 정적 실패로 막는다", async () => {
    const api = await loadApi({ mode: undefined, staticBundleText: JSON.stringify(bundleOf(RUN_A)) });

    const thrown = thrownBy(() => api.refuseServerlessRequest("static"));
    expect(thrown).toBeInstanceOf(api.StaticBundleError);
    expect(thrown).toMatchObject({ reason: "serverless" });

    const error = await rejection(api.getRuns());
    expect(error).toBeInstanceOf(api.StaticBundleError);
    expect(error).toMatchObject({ reason: "serverless" });
    expect(api.measurementRequests).toHaveLength(0);
    expect(api.serviceRequests).toHaveLength(0);
  });

  it("로컬 화면의 측정 서버 요청은 그대로 나간다", async () => {
    const api = await loadApi({ mode: undefined });

    expect(thrownBy(() => api.refuseServerlessRequest("local"))).toBeUndefined();
    await expect(api.getRuns()).resolves.toEqual({ measurementServer: true });
    expect(api.measurementRequests.map((config) => config.url)).toEqual(["/runs"]);
  });
});

describe("로컬·정적 화면은 호스팅 갈래를 타지 않는다", () => {
  it("로컬 화면의 런 상세·턴·지표는 측정 서버에서 읽고 서비스에는 묻지 않는다", async () => {
    const api = await loadApi({ mode: undefined });

    await api.getRun(RUN_A);
    await api.getTurn(RUN_A, 3);
    await api.getRunMetrics(RUN_A);

    expect(api.measurementRequests.map((config) => config.url)).toEqual([
      `/runs/${RUN_A}`,
      `/runs/${RUN_A}/turns/3`,
      `/runs/${RUN_A}/metrics`,
    ]);
    expect(api.serviceRequests).toHaveLength(0);
  });

  it("호스팅 빌드라도 정적 묶음이 실린 문서는 파일의 묶음을 읽고 서비스에 묻지 않는다", async () => {
    const api = await loadApi({ mode: "hosted", staticBundleText: JSON.stringify(bundleOf(RUN_A)) });

    await expect(api.getRun(RUN_A)).resolves.toEqual(bundleOf(RUN_A).detail);
    await expect(api.getTurn(RUN_A, 5)).resolves.toEqual({ turn: 5, attempts: [] });

    expect(api.serviceRequests).toHaveLength(0);
    expect(api.measurementRequests).toHaveLength(0);
  });

  it("호스팅 빌드에 읽지 못한 정적 묶음이 실려도 정적 실패다 — 서비스로 넘어가지 않는다", async () => {
    const api = await loadApi({ mode: "hosted", staticBundleText: "{" });

    const error = await rejection(api.getRun(RUN_A));

    expect(error).toBeInstanceOf(api.StaticBundleError);
    expect(error).toMatchObject({ reason: "broken" });
    expect(api.serviceRequests).toHaveLength(0);
  });
});

describe("호스팅 화면의 런 읽기", () => {
  it("런 상세·지표는 최신 판 묶음의 detail·metrics 그대로다", async () => {
    const api = await loadApi({ mode: "hosted" });

    await expect(api.getRun(RUN_A)).resolves.toEqual(bundleOf(RUN_A).detail);
    await expect(api.getRunMetrics(RUN_A)).resolves.toEqual(bundleOf(RUN_A).metrics);

    const bundleUrls = api.serviceRequests.map((config) => config.url).filter((url) => url?.endsWith("/bundle"));
    expect(bundleUrls).toEqual([`/api/runs/${RUN_A}/versions/${SHA_A}/bundle`]);
    expect(api.measurementRequests).toHaveLength(0);
  });

  it("턴 상세는 정적 화면과 같은 턴 찾기로 읽는다 — 배열 순번이 아니라 턴 번호로", async () => {
    const api = await loadApi({ mode: "hosted" });

    await expect(api.getTurn(RUN_A, 5)).resolves.toEqual({ turn: 5, attempts: [] });
    await expect(api.getTurn(RUN_A, 3)).resolves.toEqual({ turn: 3, attempts: [] });
  });

  it("묶음에 없는 턴은 찾지 못함으로 실패한다", async () => {
    const api = await loadApi({ mode: "hosted" });

    const error = await rejection(api.getTurn(RUN_A, 1));

    expect(error).toBeInstanceOf(api.HostedError);
    expect(error).toMatchObject({ reason: "notFound" });
    expect(api.describeHostedFailure(error, "bundle")).toEqual({ kind: "notFound" });
  });

  it("턴을 여럿 읽어도 목록과 묶음은 한 번씩만 받는다", async () => {
    const api = await loadApi({ mode: "hosted" });

    // 상세 화면은 상세·지표·턴을 한꺼번에 묻는다.
    await Promise.all([api.getRun(RUN_A), api.getRunMetrics(RUN_A), api.getTurn(RUN_A, 3)]);
    await api.getTurn(RUN_A, 5);
    await api.getTurn(RUN_A, 3);

    const urls = api.serviceRequests.map((config) => config.url);
    expect(urls.filter((url) => url === "/api/runs")).toHaveLength(1);
    expect(urls.filter((url) => url?.endsWith("/bundle"))).toHaveLength(1);
  });

  it("다른 런으로 옮겨 가면 그 런의 최신 판 묶음을 받는다 — 목록은 다시 받지 않는다", async () => {
    const api = await loadApi({ mode: "hosted" });

    await api.getRun(RUN_A);
    await expect(api.getRun(RUN_B)).resolves.toEqual(bundleOf(RUN_B).detail);

    const urls = api.serviceRequests.map((config) => config.url);
    expect(urls.filter((url) => url === "/api/runs")).toHaveLength(1);
    expect(urls.filter((url) => url?.endsWith("/bundle"))).toEqual([
      `/api/runs/${RUN_A}/versions/${SHA_A}/bundle`,
      `/api/runs/${RUN_B}/versions/${SHA_B}/bundle`,
    ]);
  });
});

describe("루프백 밖 출처에서 연 로컬 빌드", () => {
  /** 페이지 출처를 흉내 낸다. 측정 서버 요청을 막는 판정은 요청마다 이 값을 읽는다. */
  function openedAt(protocol: string, hostname: string) {
    vi.stubGlobal("location", { protocol, hostname });
  }

  it("로컬 빌드가 루프백 밖 출처에서 열리면 측정 서버로 요청을 내지 않고 로컬 빌드 안내로 막는다 — 보는 사람 컴퓨터의 측정 서버를 부르지 않는다", async () => {
    const api = await loadApi({ mode: undefined });
    const { LocalBuildElsewhereError } = await import("./labMode");
    openedAt("https:", "lab.example.test");

    const errors = await Promise.all([
      rejection(api.getRuns()),
      rejection(api.getRun(RUN_A)),
      rejection(api.getTurn(RUN_A, 3)),
      rejection(api.getRunMetrics(RUN_A)),
      rejection(api.getHealth()),
    ]);

    for (const error of errors) {
      expect(error).toBeInstanceOf(LocalBuildElsewhereError);
      expect(error).toMatchObject({ message: expect.stringContaining("호스팅 빌드(VITE_CHAT_LAB_MODE=hosted)로 다시 만든다") });
    }
    expect(api.measurementRequests).toHaveLength(0);
    expect(api.serviceRequests).toHaveLength(0);
  });

  it("막는 판정은 모드와 페이지 출처를 받는다 — 루프백 밖 출처의 로컬 빌드만 막고 루프백은 지금처럼 통과한다", async () => {
    const api = await loadApi({ mode: undefined });
    const { LocalBuildElsewhereError } = await import("./labMode");

    expect(thrownBy(() => api.refuseServerlessRequest("local", { protocol: "https:", hostname: "lab.example.test" }))).toBeInstanceOf(
      LocalBuildElsewhereError,
    );
    for (const hostname of ["localhost", "127.0.0.1", "[::1]"]) {
      expect(thrownBy(() => api.refuseServerlessRequest("local", { protocol: "http:", hostname })), hostname).toBeUndefined();
    }
  });

  it("로컬 빌드가 루프백 출처면 지금처럼 측정 서버로 요청한다", async () => {
    for (const hostname of ["localhost", "127.0.0.1", "[::1]"]) {
      const api = await loadApi({ mode: undefined });
      openedAt("http:", hostname);

      await expect(api.getRuns(), hostname).resolves.toEqual({ measurementServer: true });
      expect(api.measurementRequests.map((config) => config.url), hostname).toEqual(["/runs"]);
    }
  });

  it("파일로 연 로컬 빌드는 출처로 막지 않는다 — 정적 묶음이 없는 파일은 지금처럼 측정 서버에 묻는다", async () => {
    const api = await loadApi({ mode: undefined });
    openedAt("file:", "");

    await expect(api.getRuns()).resolves.toEqual({ measurementServer: true });
    expect(api.measurementRequests).toHaveLength(1);
  });

  it("정적·호스팅 화면은 출처와 상관없이 지금 갈래 그대로다", async () => {
    const hosted = await loadApi({ mode: "hosted" });
    openedAt("https:", "lab.example.test");
    expect(await rejection(hosted.getRuns())).toBeInstanceOf(hosted.HostedError);
    await expect(hosted.getRun(RUN_A)).resolves.toEqual(bundleOf(RUN_A).detail);

    const staticApi = await loadApi({ mode: undefined, staticBundleText: JSON.stringify(bundleOf(RUN_A)) });
    openedAt("https:", "lab.example.test");
    await expect(staticApi.getRun(RUN_A)).resolves.toEqual(bundleOf(RUN_A).detail);
    expect(await rejection(staticApi.getRuns())).toBeInstanceOf(staticApi.StaticBundleError);
    expect(staticApi.measurementRequests).toHaveLength(0);
  });
});
