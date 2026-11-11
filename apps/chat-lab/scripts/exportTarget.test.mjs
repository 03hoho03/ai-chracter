import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  confirmSameRoom,
  costGapWarning,
  decideOutputPath,
  defaultOutputName,
  findRun,
  getJson,
  isArchived,
  needsTurnExport,
  parseExportArgs,
  pickRun,
  Refusal,
  resolveTarget,
} from "./exportTarget.mjs";

/** 임시 폴더가 놓인 파일 시스템이 대소문자를 가리지 않는가(macOS 기본 APFS). 가리는 곳(CI 의 Linux)에서는 그 검사를 건너뛴다. */
function isCaseInsensitive() {
  const probe = fs.mkdtempSync(path.join(os.tmpdir(), "chat-lab-case-"));
  const name = path.basename(probe);
  try {
    return (
      fs.existsSync(path.join(path.dirname(probe), name.toUpperCase())) &&
      fs.existsSync(path.join(path.dirname(probe), name.toLowerCase()))
    );
  } finally {
    fs.rmSync(probe, { recursive: true, force: true });
  }
}

describe("parseExportArgs", () => {
  it("기본은 원문 제외·덮어쓰기 안 함이고, 런 루트는 측정 서버의 기본 루트(apps/api/probe-runs)다", () => {
    const args = parseExportArgs(["apps/api/probe-runs/2026-10-30/a"]);

    expect(args).toMatchObject({ target: "apps/api/probe-runs/2026-10-30/a", raw: false, force: false });
    expect(args.out).toBeUndefined();
    expect(args.root).toBe(fileURLToPath(new URL("../../api/probe-runs", import.meta.url)));
  });

  it("원문 포함과 덮어쓰기는 이름 붙은 플래그로만 켠다", () => {
    expect(parseExportArgs(["a", "--raw", "--force"])).toMatchObject({ target: "a", raw: true, force: true });
  });

  it("대상이 없거나 둘이거나 모르는 플래그면 던진다 — 철자가 틀린 플래그가 조용히 무시되지 않는다", () => {
    expect(() => parseExportArgs([])).toThrow();
    expect(() => parseExportArgs(["a", "b"])).toThrow();
    expect(() => parseExportArgs(["a", "--include-raw"])).toThrow();
  });
});

describe("pickRun", () => {
  const items = [
    { runId: "r1", path: "runs/a/chat.jsonl" },
    { runId: "r2", path: "runs/b/first.jsonl" },
    { runId: "r3", path: "runs/b/second.jsonl" },
    { runId: "r4", path: "top.jsonl" },
  ];

  it("드라이버 로그 경로는 그 묶음 하나다", () => {
    expect(pickRun(items, "runs/b/second.jsonl")).toEqual({ kind: "one", item: items[2] });
  });

  it("묶음 폴더에 드라이버 로그가 하나면 그 묶음이다(런 루트 자신은 `.`)", () => {
    expect(pickRun(items, "runs/a")).toEqual({ kind: "one", item: items[0] });
    expect(pickRun(items, ".")).toEqual({ kind: "one", item: items[3] });
  });

  it("폴더에 드라이버 로그가 둘 이상이면 고르지 않고 후보를 모두 낸다", () => {
    expect(pickRun(items, "runs/b")).toEqual({ kind: "many", items: [items[1], items[2]] });
  });

  it("바로 아래가 아닌 묶음이나 없는 경로는 없음이다", () => {
    expect(pickRun(items, "runs")).toEqual({ kind: "none" });
    expect(pickRun(items, "runs/c")).toEqual({ kind: "none" });
  });
});

describe("defaultOutputName", () => {
  it("드라이버 로그 이름을 따르고, 원문을 담은 파일은 이름에 raw 가 붙어 원문 없는 파일과 갈린다", () => {
    expect(defaultOutputName("chat.jsonl", false)).toBe("chat.html");
    expect(defaultOutputName("chat.jsonl", true)).toBe("chat.raw.html");
    expect(defaultOutputName("2026-10-30-long.jsonl", false)).toBe("2026-10-30-long.html");
  });
});

describe("decideOutputPath", () => {
  let base;
  let root;
  let folder;

  beforeEach(() => {
    // 실제 파일 시스템에서 본다 — 보관 폴더 판정이 경로 글자가 아니라 같은 폴더인지(장치·inode)로 가르는지가 검사 대상이다.
    base = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), "chat-lab-export-")));
    root = path.join(base, "root");
    folder = path.join(root, "runs", "a");
    fs.mkdirSync(folder, { recursive: true });
    fs.mkdirSync(path.join(root, "archive", "kept"), { recursive: true });
  });

  afterEach(() => {
    fs.rmSync(base, { recursive: true, force: true });
  });

  function decide(overrides = {}) {
    return decideOutputPath({ root, bundleFolder: folder, logName: "chat.jsonl", raw: false, force: false, ...overrides });
  }

  it("기본 위치는 그 묶음 폴더이고 원문 포함 여부로 파일 이름이 갈린다", () => {
    expect(decide()).toEqual({ kind: "write", path: path.join(folder, "chat.html") });
    expect(decide({ raw: true })).toEqual({ kind: "write", path: path.join(folder, "chat.raw.html") });
  });

  it("런 루트의 archive/ 아래 묶음에는 쓰지 않는다", () => {
    expect(decide({ bundleFolder: path.join(root, "archive", "kept") })).toMatchObject({
      kind: "refused",
      reason: "archived",
    });
  });

  it("링크로 닿은 보관 폴더도 거부한다", () => {
    fs.symlinkSync(path.join(root, "archive"), path.join(root, "linked"));

    expect(decide({ bundleFolder: path.join(root, "linked", "kept") })).toMatchObject({
      kind: "refused",
      reason: "archived",
    });
  });

  it.runIf(isCaseInsensitive())(
    "대소문자를 가리지 않는 파일 시스템에서 다른 대소문자로 적은 보관 폴더도 거부한다",
    () => {
      expect(decide({ bundleFolder: path.join(root, "ARCHIVE", "kept") })).toMatchObject({
        kind: "refused",
        reason: "archived",
      });
    },
  );

  it("런 루트가 달라도 함께 넘긴 보관 폴더(저장소의 보관 폴더 자리)는 거부한다", () => {
    const repoArchive = path.join(root, "probe-runs", "archive");
    fs.mkdirSync(path.join(repoArchive, "old"), { recursive: true });

    expect(
      decide({ bundleFolder: path.join(repoArchive, "old"), archiveDirs: [path.join(root, "archive"), repoArchive] }),
    ).toMatchObject({ kind: "refused", reason: "archived" });
  });

  it("런 루트 밖으로 나가는 출력 경로는 거부한다(`..` 로 빠져나가는 것 포함)", () => {
    expect(decide({ out: path.join(base, "elsewhere.html") })).toMatchObject({ kind: "refused", reason: "outsideRoot" });
    expect(decide({ out: `${folder}/../../../escape.html` })).toMatchObject({
      kind: "refused",
      reason: "outsideRoot",
    });
  });

  it("출력 경로를 주면 런 루트 안 그 자리에 쓴다", () => {
    const out = path.join(root, "runs", "report.html");

    expect(decide({ out })).toEqual({ kind: "write", path: out });
  });

  it("출력 경로의 폴더가 없으면 만들지 않고 거부한다", () => {
    expect(decide({ out: path.join(root, "missing", "report.html") })).toMatchObject({
      kind: "refused",
      reason: "noFolder",
    });
  });

  it("이미 있는 파일은 강제 플래그 없이는 덮지 않는다", () => {
    fs.writeFileSync(path.join(folder, "chat.html"), "손으로 고친 보고서");

    expect(decide()).toMatchObject({ kind: "refused", reason: "exists" });
    expect(decide({ force: true })).toEqual({ kind: "write", path: path.join(folder, "chat.html") });
  });

  it("그 자리에 링크나 폴더가 있으면 강제여도 쓰지 않는다", () => {
    fs.symlinkSync(path.join(base, "target.html"), path.join(folder, "chat.html"));
    fs.mkdirSync(path.join(folder, "chat.raw.html"));

    expect(decide({ force: true })).toMatchObject({ kind: "refused", reason: "notFile" });
    expect(decide({ raw: true, force: true })).toMatchObject({ kind: "refused", reason: "notFile" });
  });
});

describe("confirmSameRoom", () => {
  // 측정 서버와 이 스크립트의 런 루트가 다르면 같은 상대 경로가 다른 런을 가리킨다. 받은 묶음의 방이 대상 드라이버 로그의 방과
  // 같은지 보아, 다른 런의 데이터를 사용자가 고른 폴더에 쓰지 않는다.
  const ROOM = "11111111-1111-4111-8111-111111111111";
  const OTHER = "22222222-2222-4222-8222-222222222222";

  function log(lines) {
    return lines.map((line) => (typeof line === "string" ? line : JSON.stringify(line))).join("\n") + "\n";
  }

  it("로그 줄의 방 id 가 받은 묶음의 방과 같으면 같은 런이다 — 방 id 칸이 없는 로그인 줄·끝의 잘린 줄은 세지 않는다", () => {
    const text = log([
      { kind: "login" },
      { kind: "meta", roomId: ROOM },
      { kind: "turn", clientTurn: 1, roomId: ROOM },
      '{"kind": "turn", "roomId": "' + ROOM.slice(0, 8),
    ]);

    expect(confirmSameRoom(ROOM, text)).toEqual({ kind: "same" });
  });

  it("로그의 방이 다르면 다른 런이다", () => {
    expect(confirmSameRoom(ROOM, log([{ kind: "meta", roomId: OTHER }, { kind: "turn", roomId: OTHER }]))).toMatchObject({
      kind: "different",
    });
  });

  it("방 id 가 응답 글 같은 다른 칸에만 있으면 같은 런으로 치지 않는다 — 글자 포함이 아니라 방 id 칸을 본다", () => {
    const text = log([{ kind: "turn", roomId: OTHER, reply: `방 ${ROOM} 이야기` }]);

    expect(confirmSameRoom(ROOM, text)).toMatchObject({ kind: "different" });
  });

  it("로그에 방 id 칸이 하나도 없으면 같은 런이라고 확인할 수 없어 다른 런으로 친다", () => {
    expect(confirmSameRoom(ROOM, log([{ kind: "login" }]))).toMatchObject({ kind: "different" });
  });

  it("받은 묶음에 방 id 가 없거나 비었으면 확인할 수 없음이다 — 쓰지 않는 쪽으로 닫는다", () => {
    const text = log([{ kind: "meta", roomId: ROOM }]);

    expect(confirmSameRoom(undefined, text)).toEqual({ kind: "noRoomId" });
    expect(confirmSameRoom("", text)).toEqual({ kind: "noRoomId" });
  });
});

describe("costGapWarning", () => {
  it("현행 형식인데 원가가 비었으면(턴 기록 파일 없음) 그 묶음 폴더로 턴 기록을 내보내는 명령을 알린다", () => {
    const warning = costGapWarning({ cost: null, run: { format: "current" } }, "/runs/a");

    expect(warning).toContain("턴 기록");
    expect(warning).toContain("chat_lab_export_turns.py --run-dir /runs/a");
  });

  it("원가가 있으면 알리지 않는다 — 원가 0 원도 원가가 있는 것이다", () => {
    expect(costGapWarning({ cost: { totalUsd: 0 }, run: { format: "current" } }, "/runs/a")).toBeUndefined();
  });

  it("이전 형식은 턴 기록을 내보내도 원가가 채워지지 않아 알리지 않는다", () => {
    expect(costGapWarning({ cost: null, run: { format: "preMessageId" } }, "/runs/a")).toBeUndefined();
  });
});

describe("needsTurnExport", () => {
  it("턴 기록이 없어 원가가 빈 현행 형식 런만 턴 기록 내보내기가 필요하다", () => {
    expect(needsTurnExport({ cost: null, run: { format: "current" } })).toBe(true);
  });

  it("원가가 있으면(0 원 포함) 필요 없다", () => {
    expect(needsTurnExport({ cost: { totalUsd: 0 }, run: { format: "current" } })).toBe(false);
  });

  it("이전 형식은 턴 기록을 내보내도 원가가 채워지지 않아 필요 없다", () => {
    expect(needsTurnExport({ cost: null, run: { format: "preMessageId" } })).toBe(false);
  });
});

describe("isArchived", () => {
  let base;
  let root;

  beforeEach(() => {
    // 실제 파일 시스템에서 본다 — 경로 글자가 아니라 같은 폴더인지(장치·inode)로 가르는지가 검사 대상이다.
    base = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), "chat-lab-archived-")));
    root = path.join(base, "root");
    fs.mkdirSync(path.join(root, "runs", "a"), { recursive: true });
    fs.mkdirSync(path.join(root, "archive", "kept"), { recursive: true });
  });

  afterEach(() => {
    fs.rmSync(base, { recursive: true, force: true });
  });

  it("런 루트의 archive/ 와 그 아래는 보관 폴더이고, 런 루트와 다른 묶음 폴더는 아니다", () => {
    expect(isArchived(path.join(root, "archive"), { root })).toBe(true);
    expect(isArchived(path.join(root, "archive", "kept"), { root })).toBe(true);
    expect(isArchived(path.join(root, "runs", "a"), { root })).toBe(false);
    expect(isArchived(root, { root })).toBe(false);
  });

  it("링크로 닿은 보관 폴더도 보관 폴더로 본다", () => {
    fs.symlinkSync(path.join(root, "archive"), path.join(root, "linked"));

    expect(isArchived(path.join(root, "linked", "kept"), { root })).toBe(true);
  });

  it("이름이 archive 여도 런 루트의 보관 폴더가 아니면 보관 폴더가 아니다", () => {
    fs.mkdirSync(path.join(root, "runs", "archive"));

    expect(isArchived(path.join(root, "runs", "archive"), { root })).toBe(false);
  });

  it("런 루트가 달라도 함께 넘긴 보관 폴더(저장소의 보관 폴더 자리)는 보관 폴더다", () => {
    const repoArchive = path.join(base, "repo", "probe-runs", "archive");
    fs.mkdirSync(path.join(repoArchive, "old"), { recursive: true });

    expect(
      isArchived(path.join(repoArchive, "old"), { root, archiveDirs: [path.join(root, "archive"), repoArchive] }),
    ).toBe(true);
  });
});

describe("resolveTarget", () => {
  let base;
  let root;

  beforeEach(() => {
    base = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), "chat-lab-target-")));
    root = path.join(base, "root");
    fs.mkdirSync(path.join(root, "runs", "a"), { recursive: true });
    fs.writeFileSync(path.join(root, "runs", "a", "chat.jsonl"), "");
    fs.mkdirSync(path.join(base, "root2", "x"), { recursive: true });
  });

  afterEach(() => {
    fs.rmSync(base, { recursive: true, force: true });
  });

  it("상대 경로는 명령을 친 자리 기준으로 풀고 런 루트 기준 POSIX 경로를 낸다(런 루트 자신은 `.`)", () => {
    expect(resolveTarget({ base, root: "root", target: "root/runs/a/chat.jsonl" })).toEqual({
      root,
      target: path.join(root, "runs", "a", "chat.jsonl"),
      relativePosix: "runs/a/chat.jsonl",
    });
    expect(resolveTarget({ base: root, root: ".", target: "runs/a" })).toEqual({
      root,
      target: path.join(root, "runs", "a"),
      relativePosix: "runs/a",
    });
    expect(resolveTarget({ base, root: "root", target: "root" })).toMatchObject({ relativePosix: "." });
  });

  it("런 루트 밖은 거부한다 — `..` 로 빠져나가거나, 이름 앞부분만 같은 옆 폴더이거나, 링크로 밖을 가리켜도", () => {
    fs.symlinkSync(path.join(base, "root2"), path.join(root, "escape"));
    const outside = path.join(base, "root2", "x");

    for (const target of ["root/../root2/x", outside, path.join(root, "escape", "x")]) {
      const error = thrown(() => resolveTarget({ base, root: "root", target }));
      expect(error).toBeInstanceOf(Refusal);
      expect(error.message).toBe(`대상이 런 루트(${root}) 밖이다: ${outside}`);
    }
  });

  it("런 루트나 대상이 없으면 거부하고 푼 자리를 적는다", () => {
    const missingRoot = thrown(() => resolveTarget({ base, root: "nowhere", target: "root" }));
    const missingTarget = thrown(() => resolveTarget({ base, root: "root", target: "root/runs/zzz" }));

    expect(missingRoot).toBeInstanceOf(Refusal);
    expect(missingRoot.message).toBe(`런 루트가 없다: ${path.join(base, "nowhere")}`);
    expect(missingTarget).toBeInstanceOf(Refusal);
    expect(missingTarget.message).toBe(`대상이 없다: ${path.join(root, "runs", "zzz")}`);
  });
});

describe("findRun · getJson", () => {
  // 가짜 측정 서버 — 127.0.0.1 의 빈 포트. `/runs` 는 처음 훑은 목록, `?refresh=true` 는 다시 훑은 목록을 준다.
  let server;
  let api;
  let requests;
  let lists;

  beforeEach(async () => {
    requests = [];
    lists = { first: [], refreshed: [] };
    server = http.createServer((request, response) => {
      requests.push(request.url);
      const url = new URL(request.url, "http://lab.invalid");
      const reply = (status, body, type = "application/json") => {
        response.writeHead(status, { "content-type": type });
        response.end(typeof body === "string" ? body : JSON.stringify(body));
      };
      if (url.pathname === "/runs") {
        const items = url.searchParams.get("refresh") === "true" ? lists.refreshed : lists.first;
        reply(200, { items, discoveredAt: "2026-11-06T00:00:00Z" });
      } else if (url.pathname === "/ok") reply(200, { value: 1 });
      else if (url.pathname === "/missing") reply(404, { detail: "그런 묶음이 없다", reason: "notFound" });
      else reply(500, "Internal Server Error", "text/plain");
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    api = `http://127.0.0.1:${server.address().port}`;
  });

  afterEach(async () => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  });

  it("목록에 있으면 그 런이고 다시 훑지 않는다", async () => {
    lists.first = [{ runId: "r1", path: "runs/a/chat.jsonl" }];
    const log = vi.fn();

    expect(await findRun(api, "runs/a", { log })).toEqual(lists.first[0]);
    expect(requests).toEqual(["/runs"]);
    expect(log).not.toHaveBeenCalled();
  });

  it("목록에 없으면 다시 훑는다고 알리고 한 번 다시 훑어 찾는다", async () => {
    lists.refreshed = [{ runId: "r1", path: "runs/a/chat.jsonl" }];
    const log = vi.fn();

    expect(await findRun(api, "runs/a/chat.jsonl", { log })).toEqual(lists.refreshed[0]);
    expect(requests).toEqual(["/runs", "/runs?refresh=true"]);
    expect(log).toHaveBeenCalledWith("목록에 없어 측정 서버가 런 루트를 다시 훑는다(실데이터에서 수십 초)…");
  });

  it("다시 훑어도 없으면 거부한다", async () => {
    const error = await rejected(findRun(api, "runs/zzz", { log: vi.fn() }));

    expect(error).toBeInstanceOf(Refusal);
    expect(error.message).toBe("측정 서버의 런 목록에 runs/zzz 의 묶음이 없다");
  });

  it("폴더에 드라이버 로그가 여럿이면 후보 경로를 모두 적고 거부한다", async () => {
    lists.first = [
      { runId: "r2", path: "runs/b/first.jsonl" },
      { runId: "r3", path: "runs/b/second.jsonl" },
    ];

    const error = await rejected(findRun(api, "runs/b", { log: vi.fn() }));

    expect(error).toBeInstanceOf(Refusal);
    expect(error.message).toBe(
      "그 폴더에 드라이버 로그가 여럿이다 — 로그 경로로 하나를 고른다:\n  runs/b/first.jsonl\n  runs/b/second.jsonl",
    );
    expect(requests).toEqual(["/runs"]);
  });

  it("성공 응답은 JSON 본문이다", async () => {
    expect(await getJson(`${api}/ok`)).toEqual({ value: 1 });
  });

  it("거부 응답은 상태와 detail 을 적고, 본문이 JSON 이 아니면 (본문 없음)을 적는다", async () => {
    const withDetail = await rejected(getJson(`${api}/missing`));
    const withoutBody = await rejected(getJson(`${api}/broken`));

    expect(withDetail).toBeInstanceOf(Refusal);
    expect(withDetail.message).toBe("측정 서버가 거부했다 404: 그런 묶음이 없다");
    expect(withoutBody).toBeInstanceOf(Refusal);
    expect(withoutBody.message).toBe("측정 서버가 거부했다 500: (본문 없음)");
  });

  it("닿지 못하면 주소와 오류 코드를 적는다", async () => {
    // 방금 닫은 포트 — 연결이 거부되는 루프백 주소.
    const probe = http.createServer();
    await new Promise((resolve) => probe.listen(0, "127.0.0.1", resolve));
    const closed = `http://127.0.0.1:${probe.address().port}`;
    await new Promise((resolve) => probe.close(resolve));

    const error = await rejected(getJson(`${closed}/runs`));

    expect(error).toBeInstanceOf(Refusal);
    expect(error.message).toBe(`측정 서버에 닿지 못했다(${closed}/runs) — 먼저 띄운다: ECONNREFUSED`);
  });
});

function thrown(run) {
  try {
    run();
  } catch (error) {
    return error;
  }
  throw new Error("던지지 않았다");
}

async function rejected(promise) {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("거부되지 않았다");
}
