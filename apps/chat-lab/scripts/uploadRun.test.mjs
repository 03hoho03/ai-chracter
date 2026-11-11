// 업로드 CLI 진입점(`uploadRun.mjs`)을 자식 프로세스로 한 번씩 돌린다 — 종료 코드가 프로세스 종료 코드가 되는지와, 예상 밖 오류의
// 마지막 출력에 스택·자격 값이 실리지 않는지. 가짜 측정 서버·가짜 서비스는 이 시험 프로세스가 127.0.0.1 에 띄우고, 자식이 그리로
// 붙는다(그래서 자식은 동기 실행이 아니라 비동기로 기다린다 — 동기면 이 프로세스의 서버가 답하지 못한다).

import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

const ENTRY = fileURLToPath(new URL("./uploadRun.mjs", import.meta.url));
// 시험용 자격 값. 실제 토큰이 아니다 — 출력에 나오면 안 되는 표지다.
const CLIENT_ID = "lab-test-client-2b8d0e.access";
const CLIENT_SECRET = "lab-test-secret-Jt6Wq1Zr9Lm4Pc7Vx3Kd";
const ROOM = "11111111-1111-4111-8111-111111111111";
const RUN_PATH = "runs/a/chat.jsonl";
const RUN_ID = Buffer.from(RUN_PATH).toString("base64url");
const ITEM = { runId: RUN_ID, path: RUN_PATH, group: "runs/a", format: "current", supported: true, roomId: ROOM };

let base;
let root;
let credentialsPath;
let lab;
let service;

beforeEach(async () => {
  base = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), "chat-lab-upload-run-")));
  root = path.join(base, "probe-runs");
  fs.mkdirSync(path.join(root, "runs", "a"), { recursive: true });
  fs.writeFileSync(
    path.join(root, ...RUN_PATH.split("/")),
    [
      { kind: "meta", roomId: ROOM, base: "http://127.0.0.1:8000" },
      { kind: "turn", clientTurn: 1, roomId: ROOM },
    ]
      .map((line) => JSON.stringify(line))
      .join("\n") + "\n",
  );
  credentialsPath = path.join(base, "home", ".config", "chat-lab", "service-token.json");
  fs.mkdirSync(path.dirname(credentialsPath), { recursive: true, mode: 0o700 });
  fs.writeFileSync(credentialsPath, JSON.stringify({ clientId: CLIENT_ID, clientSecret: CLIENT_SECRET }), { mode: 0o600 });
  fs.chmodSync(credentialsPath, 0o600);
  [lab, service] = await Promise.all([startServer(labReply), startServer(() => [404, { detail: "없다", reason: "notFound" }])]);
});

afterEach(async () => {
  await Promise.all([lab, service].filter(Boolean).map((server) => server.close()));
  fs.rmSync(base, { recursive: true, force: true });
});

describe("uploadRun.mjs", () => {
  it("인자 오류는 프로세스 종료 코드 2 로 끝나고, 모르는 플래그에 준 값은 출력에 없다", async () => {
    const result = await runEntry([`--client-secret=${CLIENT_SECRET}`]);

    expect(result.code).toBe(2);
    expectNoSecrets(result);
    expect(lab.requests).toEqual([]);
    expect(service.requests).toEqual([]);
  });

  it("예상 밖 오류는 이름과 코드만 찍고 스택·자격 값을 싣지 않는다", async () => {
    // 압축 직전에 자격 값을 문구와 cause 에 실은 오류를 던지게 바꾼다 — 머리·자격 값이 어느 오류 문구에 실릴지 모르는 경우를 흉내 낸다.
    const preload = path.join(base, "gzip-throws.mjs");
    fs.writeFileSync(
      preload,
      [
        'import zlib from "node:zlib";',
        'import { syncBuiltinESMExports } from "node:module";',
        `const secret = ${JSON.stringify(`${CLIENT_ID} ${CLIENT_SECRET}`)};`,
        "zlib.gzipSync = () => {",
        '  const error = new Error("압축하다 멈췄다 " + secret, { cause: new Error(secret) });',
        '  error.code = "EBOOM";',
        "  throw error;",
        "};",
        "syncBuiltinESMExports();",
      ].join("\n"),
    );

    const result = await runEntry(
      [
        path.join(root, RUN_PATH),
        "--root",
        root,
        "--api",
        lab.url,
        "--service",
        service.url,
        "--credentials",
        credentialsPath,
      ],
      { preload },
    );

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("예상하지 못한 오류");
    expect(result.stderr).toContain("EBOOM");
    expect(result.stderr).not.toMatch(/^\s+at /m);
    expect(result.stderr).not.toContain("압축하다 멈췄다");
    expectNoSecrets(result);
    expect(service.requests).toEqual([]);
    expect(fs.existsSync(path.join(root, ".chat-lab-uploads.jsonl"))).toBe(false);
  });
});

function expectNoSecrets({ stdout, stderr }) {
  for (const secret of [CLIENT_ID, CLIENT_SECRET]) {
    expect(stdout.includes(secret), "표준 출력에 시험 자격 값이 실렸다").toBe(false);
    expect(stderr.includes(secret), "표준 오류에 시험 자격 값이 실렸다").toBe(false);
  }
}

/** 진입점을 자식 프로세스로 돌린다. 환경 변수는 PATH·HOME 만 넘겨 이 시험 프로세스의 값이 섞이지 않게 한다. */
function runEntry(args, { preload } = {}) {
  return new Promise((resolve, reject) => {
    const nodeArgs = preload === undefined ? [] : ["--import", pathToFileURL(preload).href];
    const child = spawn(process.execPath, [...nodeArgs, ENTRY, ...args], {
      cwd: base,
      env: { PATH: process.env.PATH ?? "", HOME: path.join(base, "home") },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.setEncoding("utf8").on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

/** 가짜 측정 서버 — 런 목록·통째 묶음·통과하는 올리기 머리. */
function labReply(request) {
  const url = new URL(request.url, "http://lab.invalid");
  if (url.pathname === "/runs") return [200, { items: [ITEM], discoveredAt: "2026-11-06T00:00:00Z" }];
  if (url.pathname === `/runs/${RUN_ID}/bundle`) {
    const raw = url.searchParams.get("raw") === "true";
    const detail = {
      run: ITEM,
      meta: null,
      roomStatic: null,
      turns: [],
      series: [],
      markers: [],
      statComparisons: [],
      cost: { totalUsd: 0.1 },
      unmatchedRows: [],
      mismatches: [],
      cautions: [],
    };
    return [200, { contractVersion: 1, raw, detail, metrics: {}, turns: [] }];
  }
  if (url.pathname === `/runs/${RUN_ID}/upload-header`) {
    return [
      200,
      {
        sourceCommit: { commit: "0123456789abcdef0123456789abcdef01234567", dirty: false },
        provenance: {
          passed: true,
          baseLocal: true,
          roomFound: true,
          ownerInExampleDomain: true,
          outsideUsers: 0,
          exemptedUsers: 0,
          authorInExampleDomain: true,
        },
      },
    ];
  }
  return [404, { detail: "없는 경로", reason: "notFound" }];
}

/** 127.0.0.1 의 빈 포트에 띄운 가짜 서버. handle 은 [상태, JSON 본문] 을 낸다. 받은 요청 경로를 모두 남긴다. */
async function startServer(handle) {
  const requests = [];
  const server = http.createServer((request, response) => {
    request.resume();
    request.on("end", () => {
      requests.push(`${request.method} ${request.url}`);
      const [status, body] = handle(request);
      response.writeHead(status, { "content-type": "application/json" });
      response.end(JSON.stringify(body));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    requests,
    close: () =>
      new Promise((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}
