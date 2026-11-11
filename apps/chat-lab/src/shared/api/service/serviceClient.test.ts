import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { deleteHostedRun, getHostedBundle, getHostedRuns, serviceClient } from "./serviceClient";

const SHA = "a".repeat(64);

let responseData: unknown;
const requests: InternalAxiosRequestConfig[] = [];
const originalAdapter = serviceClient.defaults.adapter;

/** 늘 200 으로 `responseData` 를 주는 가짜 어댑터 — 네트워크에 나가지 않고 나간 요청을 모은다. */
const fakeAdapter: AxiosAdapter = (config) => {
  requests.push(config);
  const response: AxiosResponse = { data: responseData, status: 200, statusText: "", headers: {}, config, request: {} };
  return Promise.resolve(response);
};

beforeEach(() => {
  requests.length = 0;
  responseData = undefined;
  serviceClient.defaults.adapter = fakeAdapter;
});

afterEach(() => {
  serviceClient.defaults.adapter = originalAdapter;
});

function onlyRequest(): InternalAxiosRequestConfig {
  expect(requests).toHaveLength(1);
  const [request] = requests;
  if (request === undefined) throw new Error("나간 요청이 없다");
  return request;
}

describe("getHostedRuns", () => {
  it("목록은 같은 출처의 /api/runs 를 GET 으로 받는다 — 측정 서버 주소를 쓰지 않는다", async () => {
    responseData = { items: [] };

    await expect(getHostedRuns()).resolves.toEqual({ items: [] });

    const request = onlyRequest();
    expect(request.method).toBe("get");
    expect(request.url).toBe("/api/runs");
    expect(request.baseURL ?? "").toBe("");
  });
});

describe("getHostedBundle", () => {
  it("묶음은 런 id·sha256 을 경로 한 마디씩 인코딩해 그 판의 묶음을 받는다", async () => {
    responseData = { contractVersion: 1 };

    await expect(getHostedBundle("a/b c", SHA)).resolves.toEqual({ contractVersion: 1 });

    const request = onlyRequest();
    expect(request.method).toBe("get");
    expect(request.url).toBe(`/api/runs/a%2Fb%20c/versions/${SHA}/bundle`);
  });
});

describe("deleteHostedRun", () => {
  it("지우기는 DELETE 로 보내고 경로와 같은 runId 를 JSON 본문에 싣는다 — 서비스는 JSON 본문 없는 지우기를 받지 않는다", async () => {
    responseData = { runId: "a/b", deletedVersions: 3 };

    await deleteHostedRun("a/b");

    const request = onlyRequest();
    expect(request.method).toBe("delete");
    expect(request.url).toBe("/api/runs/a%2Fb");
    expect(JSON.parse(String(request.data))).toEqual({ runId: "a/b" });
    expect(String(request.headers.get("Content-Type"))).toContain("application/json");
  });

  it("지운 판 수는 서비스가 센 수 그대로 돌려준다", async () => {
    responseData = { runId: "run", deletedVersions: 3 };

    await expect(deleteHostedRun("run")).resolves.toEqual({ runId: "run", deletedVersions: 3 });
  });
});
