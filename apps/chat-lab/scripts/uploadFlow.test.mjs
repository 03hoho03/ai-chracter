// 업로드 CLI(`runUpload`)를 실제 HTTP 로 본다. 측정 서버·호스팅 서비스·넘김 대상은 모두 이 시험이 127.0.0.1 의 빈 포트에 띄운
// 가짜이고, 런 루트·드라이버 로그·자격 파일은 임시 폴더에 만든다 — 실제 서비스·Cloudflare 에 닿지 않고 대화 원문도 없다.
// 자격 값은 눈에 띄는 표지 문자열이라, 모든 시험 끝에 모은 출력·콘솔·임시 폴더의 파일·측정 서버로 간 요청에 그 문자열이 없는지 본다.

import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { checkSizes, decideRecordPath, runUpload } from "./uploadFlow.mjs";

// 시험용 자격 값. 실제 토큰이 아니다 — 어느 출력·기록에도 나오면 안 되는 표지다.
const CLIENT_ID = "lab-test-client-7f3a9c.access";
const CLIENT_SECRET = "lab-test-secret-Vq8Rz2Kp6Wm3Xn9Ty5Bd";
// JSON.parse 오류 문구는 입력의 10자 남짓만 싣는다. 그 창에 통째로 들어가는 짧은 표지라야 새는지 보인다.
const SHORT_SECRET = "k7Qz9Wx2";
// 환경 변수에만 두는 값. 자격 파일 값과 달라야 서비스로 간 머리가 어느 쪽에서 왔는지 갈린다.
const ENV_CLIENT_ID = "env-only-client-93be.access";
const ENV_CLIENT_SECRET = "env-only-secret-Hs4Lc8Nf1Gj6";
const SECRETS = [CLIENT_ID, CLIENT_SECRET, SHORT_SECRET, ENV_CLIENT_ID, ENV_CLIENT_SECRET];

const MIB = 1024 * 1024;
const ROOM = "11111111-1111-4111-8111-111111111111";
const OTHER_ROOM = "22222222-2222-4222-8222-222222222222";
const RUN_PATH = "runs/a/chat.jsonl";
const RUN_ID = Buffer.from(RUN_PATH).toString("base64url");
const OTHER_RUN_ID = Buffer.from("runs/b/chat.jsonl").toString("base64url");
const LOOPBACK_BASE = "http://127.0.0.1:8000";
const RECORD_NAME = ".chat-lab-uploads.jsonl";
// 읽기 시험이 받은 목록 본문을 찍지 않는지 보는 표지.
const LIST_MARKER = "list-body-marker-5c2e";

let base;
let root;
let home;
let credentialsPath;
let lab;
let service;
let elsewhere;
let outputs;
let secretFiles;
let consoleSpies;

beforeEach(async () => {
  base = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), "chat-lab-upload-")));
  root = path.join(base, "probe-runs");
  home = path.join(base, "home");
  // 실제 런 루트처럼 보관 폴더가 함께 있는 자리에서 돈다.
  fs.mkdirSync(path.join(root, "archive", "old"), { recursive: true });
  outputs = [];
  secretFiles = new Set();
  credentialsPath = path.join(home, ".config", "chat-lab", "service-token.json");
  writeCredentials(credentialsPath, { clientId: CLIENT_ID, clientSecret: CLIENT_SECRET });
  writeLog(RUN_PATH);
  // 출력은 `io` 로만 나가야 하지만, 콘솔로 새는 구현도 잡으려고 콘솔까지 모은다.
  consoleSpies = ["log", "info", "warn", "error", "debug"].map((name) =>
    vi.spyOn(console, name).mockImplementation(() => {}),
  );
  [lab, service, elsewhere] = await Promise.all([
    startLab(),
    startService(),
    startServer(() => text(200, "다른 출처의 로그인 화면")),
  ]);
});

afterEach(async () => {
  try {
    const seen = [
      ...outputs.flatMap(({ stdout, stderr }) => [
        ["표준 출력", stdout],
        ["표준 오류", stderr],
      ]),
      ...consoleSpies.flatMap((spy) => spy.mock.calls.map((args) => ["콘솔", args.map(String).join(" ")])),
      ...filesUnder(base)
        .filter((file) => !secretFiles.has(file))
        .map((file) => [file, fs.readFileSync(file, "latin1")]),
      ...lab.requests.map((request) => ["측정 서버로 간 요청", describeRequest(request)]),
    ];
    for (const [where, content] of seen) {
      for (const secret of SECRETS) expect(content.includes(secret), `${where} 에 시험 자격 값이 실렸다`).toBe(false);
    }
    expect(elsewhere.requests, "넘김을 따라가 다른 출처로 요청했다").toEqual([]);
  } finally {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    await Promise.all([lab, service, elsewhere].filter(Boolean).map((server) => server.close()));
    fs.rmSync(base, { recursive: true, force: true });
  }
});

describe("runUpload — 인자", () => {
  it.each([
    { name: "--client-secret <값>", argv: () => ["--client-secret", CLIENT_SECRET] },
    { name: "--client-secret=<값>", argv: () => [`--client-secret=${CLIENT_SECRET}`] },
    { name: "--client-id <값>", argv: () => ["--client-id", CLIENT_ID] },
    { name: "--token <값>", argv: () => ["--token", CLIENT_SECRET] },
  ])("토큰 값을 받는 플래그는 없다 — $name 은 모르는 플래그로 2 이고 값은 출력에 없다", async ({ argv }) => {
    const result = await upload(uploadArgs({ extra: argv() }));

    expect(result.code).toBe(2);
    expectNothingSent();
  });

  it("대상 뒤에 토큰을 덧붙여도 대상이 둘이라 2 이고 값은 출력에 없다", async () => {
    const result = await upload(uploadArgs({ extra: [CLIENT_SECRET] }));

    expect(result.code).toBe(2);
    expectNothingSent();
  });

  it.each(["http://lab.example.com", "http://10.0.0.8:8000", "ftp://127.0.0.1:21", "lab.example.com", "not a url"])(
    "서비스 주소 %s 는 인자 오류다 — https 가 아니면 루프백만 받는다(서비스 토큰이 평문으로 나가지 않게)",
    async (address) => {
      const result = await upload(uploadArgs({ service: address }));

      expect(result.code).toBe(2);
      expectNothingSent();
    },
  );

  it.each(["https://lab.ddona.site", "http://127.0.0.1:9", "http://localhost:9", "http://[::1]:9"])(
    "서비스 주소 %s 는 받는다 — 인자 검사를 지나 자격 파일 검사에서 멈춘다",
    async (address) => {
      const result = await upload(uploadArgs({ service: address, credentials: path.join(base, "missing.json") }));

      expect(result.code).toBe(1);
      expect(result.stderr).toContain("자격 파일이 없다");
      expectNothingSent();
    },
  );

  // 자격 파일이 없는 자리를 줘도 2 여야 한다 — 주소 판정이 자격 파일 검사보다 먼저라, 어느 요청도(이름 풀이 포함) 나가지 않는다.
  it.each(["https://lab-ddona.site", "https://ddona.site", "https://lab.ddona.site.example.com", "https://lab.example.com"])(
    "서비스 주소 %s 는 기본 서비스 호스트도 루프백도 아니라 인자 오류다 — 오타로 서비스 토큰이 다른 호스트로 나가지 않게",
    async (address) => {
      const result = await upload(uploadArgs({ service: address, credentials: path.join(base, "missing.json") }));

      expect(result.code).toBe(2);
      expectNothingSent();
    },
  );

  it.each(["http://10.0.0.8:8791", "http://lab.example.com:8791", "https://lab.example.com", "not a url"])(
    "측정 서버 주소 %s 는 인자 오류다 — 루프백만 받는다",
    async (address) => {
      const result = await upload(uploadArgs({ api: address }));

      expect(result.code).toBe(2);
      expectNothingSent();
    },
  );

  it.each(["http://127.0.0.1:9", "http://localhost:9", "http://[::1]:9"])(
    "측정 서버 주소 %s 는 받는다 — 인자 검사를 지나 자격 파일 검사에서 멈춘다",
    async (address) => {
      const result = await upload(uploadArgs({ api: address, credentials: path.join(base, "missing.json") }));

      expect(result.code).toBe(1);
      expect(result.stderr).toContain("자격 파일이 없다");
      expectNothingSent();
    },
  );

  it.each([
    { name: "대상", extra: () => [path.join(root, RUN_PATH)] },
    { name: "--raw", extra: () => ["--raw"] },
    { name: "--exempt-email", extra: () => ["--exempt-email", "tester@example.org"] },
    { name: "--root", extra: () => ["--root", root] },
    { name: "--api", extra: () => ["--api", lab.url] },
  ])("읽기 시험에 올리기 쪽 인자($name)를 함께 주면 인자 오류다", async ({ extra }) => {
    const result = await upload([...readTestArgs(), ...extra()]);

    expect(result.code).toBe(2);
    expectNothingSent();
  });

  it("대상이 없거나 둘이면 인자 오류다", async () => {
    expect((await upload(uploadArgs({ target: null }))).code).toBe(2);
    expect((await upload(uploadArgs({ extra: [path.join(root, "runs")] }))).code).toBe(2);
    expectNothingSent();
  });
});

describe("runUpload — 자격 파일", () => {
  it.each([
    { label: "0644", mode: 0o644 },
    { label: "0400", mode: 0o400 },
    { label: "0640", mode: 0o640 },
    { label: "0700", mode: 0o700 },
  ])("권한이 0600 이 아니면($label) 거부하고 측정 서버·서비스에 요청하지 않는다", async ({ label, mode }) => {
    fs.chmodSync(credentialsPath, mode);

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("0600");
    expect(result.stderr).toContain(label);
    expectNothingSent();
  });

  it("링크면 거부한다 — 링크가 가리키는 실제 파일이 0600 이어도", async () => {
    const link = path.join(home, "linked-token.json");
    fs.symlinkSync(credentialsPath, link);

    const result = await upload(uploadArgs({ credentials: link }));

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("링크");
    expectNothingSent();
  });

  it("하드링크가 걸린 자격 파일은 거부한다 — 같은 파일의 다른 이름이 저장소 안에 있을 수 있다", async () => {
    const twin = path.join(base, "elsewhere-token.json");
    fs.linkSync(credentialsPath, twin);
    secretFiles.add(twin);

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("하드링크");
    expectNothingSent();
  });

  it("검사와 열기 사이에 링크로 바뀐 자격 파일은 열기 단계에서 링크로 거부하고 따라가 읽지 않는다", async () => {
    // 실제 자리는 링크인데 그 자리의 lstat 만 링크 대상(0600 일반 파일)을 보게 해, lstat 검사를 지난 뒤 그 자리가 링크로 바뀐
    // 경합을 흉내 낸다. 다른 자리(.git 찾기·기록 자리)의 lstat 은 그대로다.
    const target = path.join(base, "token-target", "service-token.json");
    writeCredentials(target, { clientId: CLIENT_ID, clientSecret: CLIENT_SECRET });
    const link = path.join(home, "swapped-token.json");
    fs.symlinkSync(target, link);
    const lstatSync = fs.lstatSync;
    const lstatSpy = vi
      .spyOn(fs, "lstatSync")
      .mockImplementation((file, ...rest) => lstatSync(path.resolve(String(file)) === link ? target : file, ...rest));

    const result = await upload(uploadArgs({ credentials: link }));

    expect(lstatSpy.mock.calls.some(([file]) => path.resolve(String(file)) === link), "lstat 이 그 자리를 보지 않았다").toBe(true);
    expect(result.code).toBe(1);
    expect(result.stderr).toContain("링크");
    expectNothingSent();
  });

  it("없거나 일반 파일이 아니면 거부한다", async () => {
    const missing = await upload(uploadArgs({ credentials: path.join(home, "missing.json") }));
    const folder = path.join(home, "token-folder");
    fs.mkdirSync(folder);
    const notFile = await upload(uploadArgs({ credentials: folder }));

    expect(missing.code).toBe(1);
    expect(missing.stderr).toContain("자격 파일이 없다");
    expect(notFile.code).toBe(1);
    expect(notFile.stderr).toContain("일반 파일이 아니다");
    expectNothingSent();
  });

  it("주인이 이 사용자가 아니면 거부한다 — 이 프로세스의 사용자 번호를 다르게 보이게 해서 본다", async () => {
    const uid = process.getuid();
    vi.spyOn(process, "getuid").mockReturnValue(uid + 1);

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("주인");
    expectNothingSent();
  });

  // 주인이 다른 0600 파일은 root 가 아니면 만들 수도(chown) 열 수도 없다.
  it.runIf(process.getuid?.() === 0)("주인이 다른 실제 파일도 거부한다", async () => {
    fs.chownSync(credentialsPath, 1, 1);

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("주인");
    expectNothingSent();
  });

  it.each([
    { kind: "폴더", make: (dir) => fs.mkdirSync(path.join(dir, ".git")) },
    // 작업 트리·하위 모듈의 `.git` 은 폴더가 아니라 파일이다.
    { kind: "파일", make: (dir) => fs.writeFileSync(path.join(dir, ".git"), "gitdir: /elsewhere/.git/worktrees/x\n") },
  ])("조상 폴더에 .git($kind)이 있으면 git 저장소 안이라 거부하고 그 저장소 자리를 적는다", async ({ make }) => {
    const repo = path.join(base, "dotfiles");
    const file = path.join(repo, "chat-lab", "service-token.json");
    writeCredentials(file, { clientId: CLIENT_ID, clientSecret: CLIENT_SECRET });
    make(repo);

    const result = await upload(uploadArgs({ credentials: file }));

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("git 저장소");
    expect(result.stderr).toContain(repo);
    expectNothingSent();
  });

  it("링크를 따라간 실제 자리가 git 저장소 안이어도 거부한다 — 홈의 설정 폴더를 dotfiles 저장소로 링크해 둔 경우", async () => {
    const repo = path.join(base, "dotfiles");
    fs.mkdirSync(path.join(repo, ".git"), { recursive: true });
    writeCredentials(path.join(repo, "config", "chat-lab", "service-token.json"), {
      clientId: CLIENT_ID,
      clientSecret: CLIENT_SECRET,
    });
    const linkedHome = path.join(base, "linked-home");
    fs.mkdirSync(linkedHome);
    fs.symlinkSync(path.join(repo, "config"), path.join(linkedHome, ".config"));

    const result = await upload(
      uploadArgs({ credentials: path.join(linkedHome, ".config", "chat-lab", "service-token.json") }),
    );

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("git 저장소");
    expectNothingSent();
  });

  it.each([
    { name: "JSON 이 아닌 글", content: () => SHORT_SECRET },
    { name: "따옴표 없는 값", content: () => `{"clientId": "${CLIENT_ID}", "clientSecret": ${SHORT_SECRET}}` },
    { name: "끝 쉼표", content: () => `{"clientId": "${CLIENT_ID}", "clientSecret": "${CLIENT_SECRET}",}` },
  ])("JSON 으로 읽히지 않으면($name) 거부하고 파일 글을 출력에 싣지 않는다", async ({ content }) => {
    writeSecretFile(credentialsPath, content());

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("JSON 으로 읽히지 않는다");
    expectNothingSent();
  });

  it.each([
    { name: "clientSecret 없음", value: () => ({ clientId: CLIENT_ID }), says: "두 칸" },
    { name: "clientId 없음", value: () => ({ clientSecret: CLIENT_SECRET }), says: "두 칸" },
    { name: "모르는 칸", value: () => ({ clientId: CLIENT_ID, clientSecret: CLIENT_SECRET, note: "x" }), says: "두 칸" },
    // 객체가 아닌 꼴은 문구를 정하지 않았다 — 거부만 본다.
    { name: "배열", value: () => [CLIENT_ID, CLIENT_SECRET], says: "" },
  ])("칸이 clientId·clientSecret 둘이 아니면($name) 거부한다", async ({ value, says }) => {
    writeCredentials(credentialsPath, value());

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain(says);
    expectNothingSent();
  });

  it.each([
    { name: "줄바꿈", field: "clientSecret", value: () => ({ clientId: CLIENT_ID, clientSecret: `${CLIENT_SECRET}\nX-Extra: 1` }) },
    // 끝의 CRLF 는 fetch 가 머리 값을 다듬으며 조용히 지운다 — 그 동작에 기대지 않고 먼저 막는지 본다.
    { name: "끝의 CRLF", field: "clientId", value: () => ({ clientId: `${CLIENT_ID}\r\n`, clientSecret: CLIENT_SECRET }) },
    { name: "공백", field: "clientSecret", value: () => ({ clientId: CLIENT_ID, clientSecret: `${CLIENT_SECRET} tail` }) },
    { name: "ASCII 밖 글자", field: "clientSecret", value: () => ({ clientId: CLIENT_ID, clientSecret: `${CLIENT_SECRET}값` }) },
    { name: "제어 문자", field: "clientSecret", value: () => ({ clientId: CLIENT_ID, clientSecret: `${CLIENT_SECRET}\u0000` }) },
    { name: "빈 값", field: "clientSecret", value: () => ({ clientId: CLIENT_ID, clientSecret: "" }) },
    { name: "513자", field: "clientSecret", value: () => ({ clientId: CLIENT_ID, clientSecret: CLIENT_SECRET.padEnd(513, "x") }) },
    { name: "문자열이 아닌 값", field: "clientSecret", value: () => ({ clientId: CLIENT_ID, clientSecret: 12345678 }) },
  ])("머리에 실을 수 없는 값($name)은 칸 이름만 적고 거부하며 값을 싣지 않는다", async ({ field, value }) => {
    writeCredentials(credentialsPath, value());

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain(field);
    expectNothingSent();
  });

  it("값은 512자까지, 파일은 4KiB 까지 받는다", async () => {
    const secret = CLIENT_SECRET.padEnd(512, "x");
    writeSecretFile(credentialsPath, JSON.stringify({ clientId: CLIENT_ID, clientSecret: secret }).padEnd(4096, " "));

    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    expect(uploads()[0].headers["cf-access-client-secret"]).toBe(secret);
  });

  it("4KiB 를 넘으면 거부한다", async () => {
    writeSecretFile(credentialsPath, JSON.stringify({ clientId: CLIENT_ID, clientSecret: CLIENT_SECRET }).padEnd(4097, " "));

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("4KiB");
    expectNothingSent();
  });

  it("환경 변수의 토큰은 읽지 않는다 — 자격 파일이 없으면 환경 변수에 토큰이 있어도 거부한다", async () => {
    const env = tokenEnv();
    for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value);

    const result = await upload(uploadArgs({ credentials: path.join(home, "missing.json") }), { env });

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("자격 파일이 없다");
    expectNothingSent();
  });

  it("환경 변수에 다른 토큰이 있어도 서비스로 가는 자격 머리는 자격 파일의 값이다", async () => {
    const env = tokenEnv();
    for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value);

    const result = await upload(uploadArgs(), { env });

    expect(result.code).toBe(0);
    const [request] = uploads();
    expect(request.headers["cf-access-client-id"]).toBe(CLIENT_ID);
    expect(request.headers["cf-access-client-secret"]).toBe(CLIENT_SECRET);
  });

  it("자격 파일 자리를 주지 않으면 홈의 .config/chat-lab/service-token.json 을 읽는다", async () => {
    const result = await upload(uploadArgs({ credentials: null }));

    expect(result.code).toBe(0);
    expect(uploads()[0].headers["cf-access-client-secret"]).toBe(CLIENT_SECRET);
  });
});

describe("runUpload — 대상", () => {
  it("대상의 상대 경로는 명령을 친 자리(INIT_CWD, 없으면 작업 폴더) 기준으로 푼다", async () => {
    const fromInitCwd = await upload(uploadArgs({ target: "runs/a" }), { env: { INIT_CWD: root }, cwd: home });
    const fromCwd = await upload(uploadArgs({ target: "runs/a" }), { env: {}, cwd: root });

    expect(fromInitCwd.code).toBe(0);
    expect(fromCwd.code).toBe(0);
    expect(readRecords().map((record) => record.target)).toEqual([RUN_PATH, RUN_PATH]);
  });

  it("대상이 런 루트 밖이면 측정 서버에 묻지 않고 1 이다", async () => {
    const result = await upload(uploadArgs({ target: home }));

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("밖이다");
    expectNothingSent();
  });
});

describe("runUpload — 출처", () => {
  it.each(["https://api.example.com", "http://10.1.2.3:8000", "http://127.0.0.1.example.com:8000"])(
    "meta 줄 주소(%s)가 루프백이 아니면 측정 서버가 통과라 해도 서비스에 요청하지 않고 1 이다",
    async (address) => {
      writeLog(RUN_PATH, logLines({ base: address }));
      setProvenance({ passed: true, baseLocal: false });

      const result = await upload(uploadArgs());

      expect(result.code).toBe(1);
      expect(result.stderr).toContain("루프백이 아니다");
      expect(service.requests).toEqual([]);
    },
  );

  it.each([
    { name: "숫자", base: 8000 },
    { name: "null", base: null },
    { name: "칸 없음", base: undefined },
    { name: "주소가 아닌 글", base: "not a url" },
  ])("meta 줄 주소 칸이 문자열 주소가 아니면($name) 루프백이 아니라 올리지 않는다", async ({ base: address }) => {
    writeLog(RUN_PATH, logLines({ base: address }));
    setProvenance({ passed: true, baseLocal: false });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(service.requests).toEqual([]);
  });

  it.each([LOOPBACK_BASE, "http://localhost:8000", "http://[::1]:8000"])(
    "meta 줄 주소 %s 는 루프백이라 올린다 — 대괄호를 두른 IPv6 루프백도",
    async (address) => {
      writeLog(RUN_PATH, logLines({ base: address }));

      const result = await upload(uploadArgs());

      expect(result.code).toBe(0);
      expect(uploads()).toHaveLength(1);
    },
  );

  it("meta 줄이 없고 측정 서버도 판정 없음이면 올린다", async () => {
    writeLog(RUN_PATH, logLines({ meta: false }));
    setProvenance({ baseLocal: null });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    expect(uploads()).toHaveLength(1);
  });

  it("읽히지 않는 줄은 건너뛰고 처음 meta 줄의 주소를 본다", async () => {
    writeLog(RUN_PATH, [
      '{"kind": "meta", "roomId": "' + ROOM + '", "base": "https://api.exa',
      { kind: "meta", roomId: ROOM, base: LOOPBACK_BASE },
      { kind: "meta", roomId: ROOM, base: "https://api.example.com" },
      { kind: "turn", clientTurn: 1, roomId: ROOM },
    ]);

    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    expect(uploads()).toHaveLength(1);
  });

  it.each([
    { name: "로그 판정 없음 · 측정 서버 루프백", log: { meta: false }, baseLocal: true },
    { name: "로그 루프백 · 측정 서버 판정 없음", log: {}, baseLocal: null },
    { name: "로그 루프백 · 측정 서버 루프백 아님", log: {}, baseLocal: false },
  ])(
    "로그와 측정 서버의 루프백 판정이 다르면($name) 측정 서버가 통과라 해도 올리지 않는다",
    async ({ log, baseLocal }) => {
      writeLog(RUN_PATH, logLines(log));
      setProvenance({ passed: true, baseLocal });

      const result = await upload(uploadArgs());

      expect(result.code).toBe(1);
      expect(result.stderr).toContain("측정 서버와 다르다");
      expect(service.requests).toEqual([]);
    },
  );

  it("Node 와 Python 이 다르게 푸는 주소(0x7f.0.0.1)는 측정 서버가 루프백이 아니라 하면 올리지 않는다", async () => {
    writeLog(RUN_PATH, logLines({ base: "http://0x7f.0.0.1:8000" }));
    setProvenance({ passed: false, baseLocal: false });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(service.requests).toEqual([]);
  });

  it.each([
    {
      name: "방이 이 DB 에 없음",
      provenance: { roomFound: false, ownerInExampleDomain: false, authorInExampleDomain: null },
      says: "방이 이 DB 에 없다",
    },
    { name: "방 주인이 테스트 계정 밖", provenance: { ownerInExampleDomain: false }, says: "방 주인이 테스트 계정이 아니다" },
    { name: "테스트 계정 밖 사용자", provenance: { outsideUsers: 3 }, says: "테스트 계정 밖 사용자 3명" },
  ])("출처 칸이 실패면($name) 막은 칸을 적고 서비스에 요청하지 않는다", async ({ provenance, says }) => {
    setProvenance({ passed: false, ...provenance });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain(says);
    expect(service.requests).toEqual([]);
  });

  it("작가가 테스트 계정 밖이면 표준 오류로 경고만 하고 올린다", async () => {
    setProvenance({ authorInExampleDomain: false });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    expect(result.stderr).toContain("작가가 테스트 계정 밖이다");
    expect(uploads()).toHaveLength(1);
    expect(readRecords()).toHaveLength(1);
  });

  it("커밋하지 않은 변경과 빈 원가는 경고만 하고 올린다", async () => {
    lab.header.sourceCommit.dirty = true;
    lab.bundleFor = (raw) => makeBundle({ raw, run: lab.items[0], cost: null });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    expect(result.stderr).toContain("커밋하지 않은 변경");
    expect(result.stderr).toContain("턴 기록을 내보낸 뒤 다시 올린다");
    expect(uploads()).toHaveLength(1);
  });

  it("측정 서버가 올리기 머리를 거부하면 그 detail 을 그대로 적고 올리지 않는다", async () => {
    lab.headerReply = json(503, { detail: "DB 에 닿지 않는다: OperationalError", reason: "dbUnavailable" });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("DB 에 닿지 않는다: OperationalError");
    expect(service.requests).toEqual([]);
  });

  it("올리기 머리 요청은 JSON 본문에 예외 이메일을 싣고, 없으면 빈 목록이다", async () => {
    await upload(uploadArgs({ extra: ["--exempt-email", "a@example.org", "--exempt-email", "b@example.org"] }));
    await upload(uploadArgs());

    const [withEmails, withoutEmails] = headerRequests();
    expect(withEmails.url).toBe(`/runs/${RUN_ID}/upload-header`);
    expect(withEmails.headers["content-type"]).toMatch(/^application\/json/);
    expect(JSON.parse(withEmails.body.toString("utf8"))).toEqual({ exemptEmails: ["a@example.org", "b@example.org"] });
    expect(JSON.parse(withoutEmails.body.toString("utf8"))).toEqual({ exemptEmails: [] });
  });
});

describe("runUpload — 묶음", () => {
  it("원문 포함 플래그면 측정 서버에 raw=true 로 묻고, 경고하고, 기록에 raw 를 남긴다", async () => {
    const result = await upload(uploadArgs({ extra: ["--raw"] }));

    expect(result.code).toBe(0);
    expect(bundleRequests().map(rawParam)).toEqual(["true"]);
    expect(result.stderr).toContain("원문 포함으로 올린다");
    expect(readRecords()).toMatchObject([{ raw: true }]);
  });

  it("원문 포함 플래그가 없으면 raw=false 로 묻고 원문 경고가 없다", async () => {
    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    expect(bundleRequests().map(rawParam)).toEqual(["false"]);
    expect(result.stderr).not.toContain("원문 포함으로 올린다");
    expect(readRecords()).toMatchObject([{ raw: false }]);
  });

  it.each([
    { name: "원문 제외로 물었는데 원문 포함", flags: [], served: true },
    { name: "원문 포함으로 물었는데 원문 제외", flags: ["--raw"], served: false },
  ])("측정 서버가 요청과 다른 원문 여부를 주면($name) 올리지 않는다", async ({ flags, served }) => {
    lab.bundleFor = () => makeBundle({ raw: served, run: lab.items[0] });

    const result = await upload(uploadArgs({ extra: flags }));

    expect(result.code).toBe(1);
    expect(service.requests).toEqual([]);
  });

  it("묶음의 런 id 가 고른 런과 다르면 올리기 머리도 묻지 않고 올리지 않는다", async () => {
    lab.bundleFor = (raw) => makeBundle({ raw, run: { ...lab.items[0], runId: OTHER_RUN_ID } });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(headerRequests()).toEqual([]);
    expect(service.requests).toEqual([]);
  });

  it("묶음의 방이 대상 드라이버 로그의 방과 다르면 올리지 않는다", async () => {
    lab.bundleFor = (raw) => makeBundle({ raw, run: { ...lab.items[0], roomId: OTHER_ROOM } });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(service.requests).toEqual([]);
  });

  it.each([
    { name: "0", value: 0 },
    { name: "문자열", value: "1" },
    { name: "소수", value: 1.5 },
    { name: "없음", value: undefined },
  ])("계약 판이 1 이상 정수가 아니면($name) 올리지 않는다", async ({ value }) => {
    lab.bundleFor = (raw) => makeBundle({ raw, run: lab.items[0], contractVersion: value });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(service.requests).toEqual([]);
  });

  it("서비스가 받은 본문을 풀면 측정 서버가 준 바이트 그대로이고, 올리기 머리와 자격 두 머리가 왔다", async () => {
    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    const [request] = uploads();
    const served = lab.served.at(-1);
    expect(request.url).toBe(`/api/runs/${RUN_ID}/versions`);
    expect(request.headers["content-type"]).toBe("application/gzip");
    // 측정 서버가 준 묶음은 들여쓰기와 \u 이스케이프가 든 바이트라, 다시 직렬화하면 여기서 어긋난다.
    expect(zlib.gunzipSync(request.body).equals(served)).toBe(true);
    const header = request.headers["x-lab-upload-header"];
    expect(header).not.toContain("\n");
    expect(JSON.parse(header)).toEqual(lab.header);
    expect(request.headers["cf-access-client-id"]).toBe(CLIENT_ID);
    expect(request.headers["cf-access-client-secret"]).toBe(CLIENT_SECRET);
  });

  it("측정 서버로 가는 요청에는 자격 머리가 없다", async () => {
    await upload(uploadArgs());

    expect(lab.requests.length).toBeGreaterThan(0);
    for (const request of lab.requests) {
      expect(request.headers).not.toHaveProperty("cf-access-client-id");
      expect(request.headers).not.toHaveProperty("cf-access-client-secret");
    }
  });

  it("묶음이 꼭 32MiB 면 올리고, 1바이트라도 넘으면 서비스에 요청하지 않는다", async () => {
    let padding = "";
    lab.bundleFor = (raw) => ({ ...makeBundle({ raw, run: lab.items[0] }), padding });
    padding = "a".repeat(32 * MIB - Buffer.byteLength(asciiJson(lab.bundleFor(false))));

    const atLimit = await upload(uploadArgs());

    expect(lab.served.at(-1).length).toBe(32 * MIB);
    expect(atLimit.code).toBe(0);
    expect(uploads().length).toBe(1);

    padding += "a";
    const overLimit = await upload(uploadArgs());

    expect(lab.served.at(-1).length).toBe(32 * MIB + 1);
    expect(overLimit.code).toBe(1);
    expect(uploads().length).toBe(1);
  }, 60_000);

  it("압축한 묶음이 8MiB 를 넘으면 서비스에 요청하지 않는다", async () => {
    // 무작위 바이트의 base64 는 gzip 으로 거의 줄지 않아, 푼 크기는 상한 안이고 압축 크기만 상한을 넘는다.
    const noise = crypto.randomBytes(10 * MIB).toString("base64");
    lab.bundleFor = (raw) => ({ ...makeBundle({ raw, run: lab.items[0] }), noise });

    const result = await upload(uploadArgs());

    const served = lab.served.at(-1);
    expect(served.length).toBeLessThanOrEqual(32 * MIB);
    expect(zlib.gzipSync(served).length).toBeGreaterThan(8 * MIB);
    expect(result.code).toBe(1);
    // 실패 때 수 MiB 본문을 찍지 않으려고 개수로 본다.
    expect(service.requests.length).toBe(0);
  }, 60_000);
});

describe("checkSizes", () => {
  it("크기 상한과 같은 크기는 받고 1바이트 넘으면 거부한다 — 푼 바이트 32MiB, 압축 바이트 8MiB", () => {
    expect(checkSizes({ uncompressedSize: 32 * MIB })).toEqual({ kind: "ok" });
    expect(checkSizes({ uncompressedSize: 32 * MIB + 1 })).toMatchObject({ kind: "tooLarge", part: "uncompressed" });
    expect(checkSizes({ uncompressedSize: 32 * MIB, compressedSize: 8 * MIB })).toEqual({ kind: "ok" });
    expect(checkSizes({ uncompressedSize: 32 * MIB, compressedSize: 8 * MIB + 1 })).toMatchObject({
      kind: "tooLarge",
      part: "compressed",
    });
  });
});

describe("runUpload — 서비스 응답", () => {
  it.each([
    { status: 201, kind: "created", says: "올렸다" },
    { status: 200, kind: "exists", says: "이미 있다" },
    { status: 200, kind: "restored", says: "되살렸다" },
  ])("서비스가 $status $kind 로 답하면 0 이고 기록 한 줄을 덧붙인다", async ({ status, kind, says }) => {
    service.uploadReply = (request, runId) =>
      json(status, { runId, sha256: sha256Hex(zlib.gunzipSync(request.body)), status: kind, versionNumber: 4 });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    expect(result.stdout).toContain(says);
    expect(readRecords()).toMatchObject([{ status: kind, versionNumber: 4 }]);
  });

  it.each([302, 307])(
    "서비스가 %i 로 넘기면 따라가지 않고, 토큰 만료 가능성을 말하고, 넘긴 주소를 찍지 않으며, 기록하지 않는다",
    async (status) => {
      const location = `${elsewhere.url}/cdn-cgi/access/login/lab-redirect-target`;
      service.uploadReply = () => ({ status, headers: { location }, body: "" });

      const result = await upload(uploadArgs());

      expect(result.code).toBe(1);
      expect(result.stderr).toContain(String(status));
      expect(result.stderr).toContain("만료");
      expect(`${result.stdout}${result.stderr}`).not.toContain("lab-redirect-target");
      expect(`${result.stdout}${result.stderr}`).not.toContain(elsewhere.url);
      expect(readRecords()).toEqual([]);
    },
  );

  it.each([
    { status: 401, reply: json(401, { detail: "인증이 없다", reason: "unauthenticated" }) },
    { status: 403, reply: text(403, "<!doctype html><title>Forbidden</title>", "text/html; charset=utf-8") },
  ])("서비스가 $status 이면 토큰 만료 가능성을 말하고 기록하지 않는다", async ({ status, reply }) => {
    service.uploadReply = () => reply;

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain(String(status));
    expect(result.stderr).toContain("만료");
    expect(readRecords()).toEqual([]);
  });

  it.each([
    { name: "HTML", reply: () => text(200, "<!doctype html><title>로그인</title>", "text/html; charset=utf-8") },
    { name: "JSON 이라면서 JSON 이 아닌 본문", reply: () => text(201, "<html>", "application/json") },
    {
      name: "본문은 맞는데 content-type 이 글",
      reply: (request, runId) =>
        text(
          201,
          JSON.stringify({ runId, sha256: sha256Hex(zlib.gunzipSync(request.body)), status: "created", versionNumber: 1 }),
          "text/plain",
        ),
    },
  ])("JSON 아닌 2xx($name)는 실패이고 기록하지 않는다", async ({ reply }) => {
    service.uploadReply = reply;

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("JSON 이 아니다");
    expect(readRecords()).toEqual([]);
  });

  it.each([
    { name: "sha256", change: { sha256: "f".repeat(64) } },
    { name: "런 id", change: { runId: OTHER_RUN_ID } },
  ])("서비스가 돌려준 $name 이 올린 것과 다르면 실패이고 기록하지 않는다", async ({ change }) => {
    service.uploadReply = (request, runId) =>
      json(201, { runId, sha256: sha256Hex(zlib.gunzipSync(request.body)), status: "created", versionNumber: 1, ...change });

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("다르다");
    expect(readRecords()).toEqual([]);
  });

  it.each([
    { status: 404, body: { detail: "없다", reason: "notFound" }, says: "404" },
    { status: 413, body: { detail: "압축 바이트가 상한을 넘는다", reason: "tooLarge" }, says: "tooLarge" },
    { status: 422, body: { detail: "출처 칸이 실패다", reason: "provenanceFailed" }, says: "provenanceFailed" },
    {
      status: 422,
      body: { detail: [{ loc: ["header", "x-lab-upload-header"], msg: "Field required", type: "missing" }] },
      says: "Field required",
    },
    { status: 503, body: { detail: "DB 에 닿지 않는다", reason: "dbUnavailable" }, says: "dbUnavailable" },
    { status: 500, body: { detail: "서비스 안 오류", reason: "internal" }, says: "500" },
  ])("서비스가 $status 로 거부하면 상태와 까닭($says)을 적고 기록하지 않는다", async ({ status, body, says }) => {
    service.uploadReply = () => json(status, body);

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain(String(status));
    expect(result.stderr).toContain(says);
    expect(readRecords()).toEqual([]);
  });

  it("서비스에 닿지 못하면 오류 코드만 적고 기록하지 않는다", async () => {
    const result = await upload(uploadArgs({ service: await closedAddress() }));

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("ECONNREFUSED");
    expect(result.stderr).not.toContain("fetch failed");
    expect(readRecords()).toEqual([]);
  });

  it("서비스가 응답 도중 연결을 끊으면 오류 코드만 적고 기록하지 않는다", async () => {
    service.uploadReply = (_request, _runId, response) => {
      response.socket.destroy();
      return undefined;
    };

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("UND_ERR_SOCKET");
    expect(result.stderr).not.toContain("fetch failed");
    expect(result.stderr).not.toContain("other side closed");
    expect(readRecords()).toEqual([]);
  });
});

describe("runUpload — 올리기 기록", () => {
  it("올리면 런 루트 바로 아래 기록에 한 줄을 덧붙이고, 줄에는 드라이버 줄 종류(kind) 칸이 없다", async () => {
    const result = await upload(uploadArgs());

    expect(result.code).toBe(0);
    const text = fs.readFileSync(path.join(root, RECORD_NAME), "utf8");
    expect(text.endsWith("\n")).toBe(true);
    const lines = text.trimEnd().split("\n");
    expect(lines).toHaveLength(1);
    const record = JSON.parse(lines[0]);
    // 측정 서버의 묶음 찾기는 런 루트 아래 모든 .jsonl 의 첫 줄 kind 로 드라이버 로그를 가린다.
    expect(record).not.toHaveProperty("kind");
    const served = lab.served.at(-1);
    expect(record).toEqual({
      at: expect.any(String),
      service: service.url,
      runId: RUN_ID,
      target: RUN_PATH,
      raw: false,
      sha256: sha256Hex(served),
      status: "created",
      versionNumber: 1,
      compressedSize: uploads()[0].body.length,
      uncompressedSize: served.length,
    });
    expect(new Date(record.at).toISOString()).toBe(record.at);
  });

  it("두 번 올리면 앞 기록을 지우지 않고 줄을 덧붙인다", async () => {
    const earlier = { at: "2026-11-01T00:00:00.000Z", note: "앞선 기록" };
    fs.writeFileSync(path.join(root, RECORD_NAME), `${JSON.stringify(earlier)}\n`);

    expect((await upload(uploadArgs())).code).toBe(0);
    expect((await upload(uploadArgs())).code).toBe(0);

    const records = readRecords();
    expect(records[0]).toEqual(earlier);
    expect(records.slice(1).map((record) => record.status)).toEqual(["created", "exists"]);
  });

  it("런 루트가 보관 폴더 아래면 측정 서버·서비스에 요청하기 전에 거부한다", async () => {
    // 런 루트의 archive/ 가 런 루트를 품은 보관 폴더를 가리키는 링크다. 장치·inode 로 보면 런 루트가 그 보관 폴더 아래다.
    const shelf = path.join(base, "shelf");
    const shelvedRoot = path.join(shelf, "probe-runs");
    writeLog(RUN_PATH, logLines(), shelvedRoot);
    fs.symlinkSync(shelf, path.join(shelvedRoot, "archive"));

    const result = await upload(uploadArgs({ root: shelvedRoot, target: path.join(shelvedRoot, RUN_PATH) }));

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("archive/");
    expectNothingSent();
    expect(fs.existsSync(path.join(shelvedRoot, RECORD_NAME))).toBe(false);
  });

  it("대상이 보관 폴더 아래여도 기록 자리(런 루트)가 맞으면 올리고, 보관 폴더에는 아무것도 쓰지 않는다", async () => {
    const archived = "archive/old/chat.jsonl";
    writeLog(archived);
    lab.items = [itemFor(archived)];

    const result = await upload(uploadArgs({ target: path.join(root, archived) }));

    expect(result.code).toBe(0);
    expect(readRecords()).toMatchObject([{ target: archived, runId: itemFor(archived).runId }]);
    expect(fs.readdirSync(path.join(root, "archive", "old"))).toEqual(["chat.jsonl"]);
  });

  it.each([
    { name: "링크", make: (file) => fs.symlinkSync(path.join(base, "outside.jsonl"), file) },
    { name: "폴더", make: (file) => fs.mkdirSync(file) },
  ])("기록 자리에 일반 파일이 아닌 것($name)이 있으면 측정 서버·서비스에 요청하기 전에 거부한다", async ({ make }) => {
    make(path.join(root, RECORD_NAME));

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("일반 파일이 아닌 것");
    expectNothingSent();
    expect(fs.existsSync(path.join(base, "outside.jsonl"))).toBe(false);
  });

  it("올리는 사이 기록 자리가 링크로 바뀌면 따라 쓰지 않고 1 이며 판과 sha256 을 알린다", async () => {
    const outside = path.join(base, "outside.jsonl");
    service.uploadReply = (request, runId) => {
      fs.symlinkSync(outside, path.join(root, RECORD_NAME));
      return service.accept(request, runId);
    };

    const result = await upload(uploadArgs());

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("올렸지만 올리기 기록에 쓰지 못했다");
    expect(result.stderr).toContain(sha256Hex(lab.served.at(-1)).slice(0, 12));
    expect(fs.existsSync(outside)).toBe(false);
  });
});

describe("decideRecordPath", () => {
  it("기록 자리는 런 루트 바로 아래 .chat-lab-uploads.jsonl 이다 — 아직 없어도, 이미 일반 파일로 있어도", () => {
    const expected = { kind: "write", path: path.join(root, RECORD_NAME) };

    expect(decideRecordPath({ root })).toEqual(expected);
    fs.writeFileSync(path.join(root, RECORD_NAME), "");
    expect(decideRecordPath({ root })).toEqual(expected);
  });

  it("런 루트가 함께 넘긴 보관 폴더(저장소의 보관 폴더 자리)이거나 그 아래면 거부한다", () => {
    const repoArchive = path.join(base, "repo", "probe-runs", "archive");
    const inner = path.join(repoArchive, "2026-10");
    fs.mkdirSync(inner, { recursive: true });

    expect(decideRecordPath({ root: repoArchive, archiveDirs: [repoArchive] })).toMatchObject({
      kind: "refused",
      reason: "archived",
    });
    expect(decideRecordPath({ root: inner, archiveDirs: [repoArchive] })).toMatchObject({
      kind: "refused",
      reason: "archived",
    });
  });

  it("기록 자리에 링크나 폴더가 있으면 거부한다", () => {
    fs.symlinkSync(path.join(base, "outside.jsonl"), path.join(root, RECORD_NAME));
    expect(decideRecordPath({ root })).toMatchObject({ kind: "refused", reason: "notFile" });

    fs.rmSync(path.join(root, RECORD_NAME));
    fs.mkdirSync(path.join(root, RECORD_NAME));
    expect(decideRecordPath({ root })).toMatchObject({ kind: "refused", reason: "notFile" });
  });

  describe("런 루트가 git 작업 트리 안일 때", () => {
    let repo;
    let runRoot;

    beforeEach(() => {
      // 이 머신의 전역 git 설정·전역 무시 파일이 판정에 섞이지 않게 홈·설정 자리를 임시 폴더로 돌린다.
      vi.stubEnv("HOME", base);
      vi.stubEnv("XDG_CONFIG_HOME", base);
      vi.stubEnv("GIT_CONFIG_NOSYSTEM", "1");
      repo = path.join(base, "checkout");
      runRoot = path.join(repo, "runs-elsewhere");
      fs.mkdirSync(runRoot, { recursive: true });
      execFileSync("git", ["init", "-q", repo], { stdio: "ignore" });
    });

    it("기록 자리가 그 저장소의 무시 대상이 아니면 거부한다 — 커밋되면 런 id·경로·sha 가 저장소에 남는다", () => {
      expect(decideRecordPath({ root: runRoot })).toMatchObject({ kind: "refused", reason: "notIgnored" });
      expect(fs.existsSync(path.join(runRoot, RECORD_NAME))).toBe(false);
    });

    it("그 저장소의 .gitignore 가 기록 파일을 무시하면 받는다", () => {
      fs.writeFileSync(path.join(repo, ".gitignore"), `${RECORD_NAME}\n`);

      expect(decideRecordPath({ root: runRoot })).toEqual({ kind: "write", path: path.join(runRoot, RECORD_NAME) });
    });
  });
});

describe("runUpload — 읽기 시험", () => {
  it("읽기 시험은 GET /api/runs 하나를 보내 상태 코드만 찍고, 본문·기록을 남기지 않는다", async () => {
    const result = await upload(readTestArgs());

    expect(result.code).toBe(0);
    expect(result.stdout).toContain("GET /api/runs → 200");
    expect(`${result.stdout}${result.stderr}`).not.toContain(LIST_MARKER);
    expect(service.requests.map((request) => `${request.method} ${request.url}`)).toEqual(["GET /api/runs"]);
    expect(service.requests[0].headers["cf-access-client-id"]).toBe(CLIENT_ID);
    expect(service.requests[0].headers["cf-access-client-secret"]).toBe(CLIENT_SECRET);
    expect(lab.requests).toEqual([]);
    expect(fs.existsSync(path.join(root, RECORD_NAME))).toBe(false);
  });

  it.each([404, 302])("읽기 시험은 %i 도 그 코드로 찍고 0 이다 — 판정하지 않고 넘김도 따라가지 않는다", async (status) => {
    service.listReply =
      status === 302
        ? { status, headers: { location: `${elsewhere.url}/cdn-cgi/access/login` }, body: "" }
        : json(status, { detail: "없다", reason: "notFound" });

    const result = await upload(readTestArgs());

    expect(result.code).toBe(0);
    expect(result.stdout).toContain(`GET /api/runs → ${status}`);
    expect(fs.existsSync(path.join(root, RECORD_NAME))).toBe(false);
  });

  it("읽기 시험이 서비스에 닿지 못하면 오류 코드를 적고 1 이다", async () => {
    const result = await upload(readTestArgs(await closedAddress()));

    expect(result.code).toBe(1);
    expect(result.stderr).toContain("ECONNREFUSED");
  });

  it("읽기 시험도 자격 파일 검사를 먼저 한다 — 권한이 틀리면 요청 없이 1 이다", async () => {
    fs.chmodSync(credentialsPath, 0o644);

    const result = await upload(readTestArgs());

    expect(result.code).toBe(1);
    expectNothingSent();
  });
});

// ── 도움 함수 ─────────────────────────────────────────────────────────────────────────────────────────

async function upload(argv, overrides = {}) {
  const captured = { stdout: "", stderr: "" };
  outputs.push(captured);
  const sink = (key) => ({
    write(chunk, ...rest) {
      captured[key] += String(chunk);
      rest.find((value) => typeof value === "function")?.();
      return true;
    },
  });
  const code = await runUpload(argv, {
    env: {},
    cwd: base,
    homedir: home,
    stdout: sink("stdout"),
    stderr: sink("stderr"),
    ...overrides,
  });
  return { code, stdout: captured.stdout, stderr: captured.stderr };
}

/** 기본은 가짜 측정 서버·가짜 서비스·임시 자격 파일로 대상 런 하나를 올리는 인자. 값이 null 인 자리는 빼고, extra 는 끝에 붙인다. */
function uploadArgs(options = {}) {
  const pick = (key, fallback) => (key in options ? options[key] : fallback);
  const target = pick("target", path.join(root, RUN_PATH));
  const flags = [
    ["--root", pick("root", root)],
    ["--api", pick("api", lab.url)],
    ["--service", pick("service", service.url)],
    ["--credentials", pick("credentials", credentialsPath)],
  ]
    .filter(([, value]) => value !== null)
    .flat();
  return [...(target === null ? [] : [target]), ...flags, ...(options.extra ?? [])];
}

function readTestArgs(serviceUrl = service.url) {
  return ["--read-test", "--service", serviceUrl, "--credentials", credentialsPath];
}

function expectNothingSent() {
  expect(lab.requests, "측정 서버에 요청했다").toEqual([]);
  expect(service.requests, "서비스에 요청했다").toEqual([]);
}

function uploads() {
  return service.requests.filter((request) => request.method === "POST");
}

function bundleRequests() {
  return lab.requests.filter((request) => request.method === "GET" && /\/bundle(\?|$)/.test(request.url));
}

function headerRequests() {
  return lab.requests.filter((request) => request.method === "POST");
}

function rawParam(request) {
  return new URL(request.url, "http://lab.invalid").searchParams.get("raw");
}

function readRecords() {
  const file = path.join(root, RECORD_NAME);
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter((line) => line !== "")
    .map((line) => JSON.parse(line));
}

function tokenEnv() {
  return {
    CF_ACCESS_CLIENT_ID: ENV_CLIENT_ID,
    CF_ACCESS_CLIENT_SECRET: ENV_CLIENT_SECRET,
    CHAT_LAB_CLIENT_ID: ENV_CLIENT_ID,
    CHAT_LAB_CLIENT_SECRET: ENV_CLIENT_SECRET,
    CHAT_LAB_SERVICE_TOKEN: ENV_CLIENT_SECRET,
  };
}

function writeCredentials(file, value) {
  writeSecretFile(file, JSON.stringify(value));
}

/** 자격 파일 꼴 그대로(0700 폴더 안 0600 파일) 쓴다. 이 파일은 비밀이 든 것이 정상이라 끝의 새는지 검사에서 뺀다. */
function writeSecretFile(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file, content, { mode: 0o600 });
  fs.chmodSync(file, 0o600);
  secretFiles.add(file);
}

/** 합성 드라이버 로그 줄 — 방 id 와 meta 줄 주소만 있고 대화 글은 없다. `base` 를 undefined 로 주면 주소 칸이 빠진다. */
function logLines(options = {}) {
  const address = "base" in options ? options.base : LOOPBACK_BASE;
  return [
    { kind: "login", ok: true },
    ...(options.meta === false ? [] : [{ kind: "meta", roomId: ROOM, base: address }]),
    { kind: "turn", clientTurn: 1, roomId: ROOM },
    { kind: "turn", clientTurn: 2, roomId: ROOM },
  ];
}

function writeLog(relativePath, lines = logLines(), runRoot = root) {
  const file = path.join(runRoot, ...relativePath.split("/"));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${lines.map((line) => (typeof line === "string" ? line : JSON.stringify(line))).join("\n")}\n`);
}

function itemFor(relativePath) {
  return {
    runId: Buffer.from(relativePath).toString("base64url"),
    path: relativePath,
    group: path.posix.dirname(relativePath),
    format: "current",
    supported: true,
    roomId: ROOM,
    storyName: "합성 이야기",
    turnCount: 2,
    startedAt: "2026-11-05T10:00:00Z",
    endedAt: "2026-11-05T10:05:00Z",
    sentChatModels: [],
    sentChatModelsFrom: null,
    configuredChatModels: [],
    costUsd: 0.25,
    unpricedCalls: 0,
    costIsLowerBound: false,
  };
}

/** 합성 통째 묶음. cost·contractVersion 은 칸을 주면 그 값(undefined 면 칸이 빠진다), 안 주면 기본값이다. */
function makeBundle(options) {
  const { raw, run } = options;
  const cost = "cost" in options ? options.cost : { totalUsd: 0.25 };
  const contractVersion = "contractVersion" in options ? options.contractVersion : 1;
  return {
    contractVersion,
    raw,
    detail: {
      run,
      meta: null,
      roomStatic: null,
      turns: [],
      series: [],
      markers: [],
      statComparisons: [],
      cost,
      unmatchedRows: [],
      mismatches: [],
      cautions: [],
    },
    metrics: {},
    turns: [],
  };
}

function uploadHeader() {
  return {
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
  };
}

function setProvenance(overrides) {
  lab.header.provenance = { ...lab.header.provenance, ...overrides };
}

/** 측정 서버가 주는 꼴을 흉내 낸 바이트 — 들여쓰기와 ASCII 밖 글자의 \u 이스케이프가 있어, 다시 직렬화하면 바이트가 달라진다. */
function asciiJson(value) {
  return JSON.stringify(value, null, 2).replace(
    /[\u0080-￿]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

function sha256Hex(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function json(status, value) {
  return { status, headers: { "content-type": "application/json" }, body: JSON.stringify(value) };
}

function text(status, body, contentType = "text/plain; charset=utf-8") {
  return { status, headers: { "content-type": contentType }, body };
}

function describeRequest(request) {
  return `${request.method} ${request.url}\n${JSON.stringify(request.headers)}\n${request.body.toString("latin1")}`;
}

/** 임시 폴더 아래 일반 파일 전부. 링크는 따라가지 않는다(자격 파일을 가리키는 링크·되도는 링크가 있다). */
function filesUnder(dir) {
  const found = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...filesUnder(full));
    else if (entry.isFile()) found.push(full);
  }
  return found;
}

/** 방금 닫은 포트 — 연결이 거부되는 루프백 주소. */
async function closedAddress() {
  const server = http.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  return `http://127.0.0.1:${port}`;
}

/** 127.0.0.1 의 빈 포트에 띄운 가짜 서버. 받은 요청(본문 포함)을 모두 남긴다. handle 이 undefined 를 내면 응답은 handle 몫이다. */
async function startServer(handle) {
  const requests = [];
  const server = http.createServer((request, response) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      const received = { method: request.method, url: request.url, headers: request.headers, body: Buffer.concat(chunks) };
      requests.push(received);
      let reply;
      try {
        reply = handle(received, response);
      } catch (error) {
        reply = text(500, `시험 서버가 멈췄다: ${error}`);
      }
      if (reply === undefined) return;
      response.writeHead(reply.status, reply.headers);
      response.end(reply.body);
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

/** 가짜 측정 서버 — 런 목록·통째 묶음·올리기 머리. 묶음 바이트는 준 그대로 served 에 남긴다. */
async function startLab() {
  const state = {
    items: [itemFor(RUN_PATH)],
    bundleFor: (raw) => makeBundle({ raw, run: state.items[0] }),
    header: uploadHeader(),
    headerReply: undefined,
    served: [],
  };
  const server = await startServer((request) => {
    const url = new URL(request.url, "http://lab.invalid");
    if (request.method === "GET" && url.pathname === "/runs") {
      return json(200, { items: state.items, discoveredAt: "2026-11-06T00:00:00Z" });
    }
    const bundle = /^\/runs\/([^/]+)\/bundle$/.exec(url.pathname);
    if (request.method === "GET" && bundle) {
      const raw = url.searchParams.get("raw");
      if (raw !== "true" && raw !== "false") {
        return json(422, { detail: [{ loc: ["query", "raw"], msg: "Field required", type: "missing" }] });
      }
      if (!state.items.some((item) => item.runId === decodeURIComponent(bundle[1]))) {
        return json(404, { detail: "그런 묶음이 없다", reason: "notFound" });
      }
      const bytes = Buffer.from(asciiJson(state.bundleFor(raw === "true")), "utf8");
      state.served.push(bytes);
      return { status: 200, headers: { "content-type": "application/json" }, body: bytes };
    }
    if (request.method === "POST" && /^\/runs\/[^/]+\/upload-header$/.test(url.pathname)) {
      // 여러 줄 JSON 으로 준다 — 서비스로 보내는 머리는 한 줄로 다시 써야 한다.
      return (
        state.headerReply ?? {
          status: 200,
          headers: { "content-type": "application/json" },
          body: JSON.stringify(state.header, null, 2),
        }
      );
    }
    return json(404, { detail: "없는 경로", reason: "notFound" });
  });
  return Object.assign(state, server);
}

/** 가짜 호스팅 서비스 — 기본은 받은 gzip 을 풀어 sha256 으로 판을 가리고, 같은 내용이면 exists 로 답한다. */
async function startService() {
  const state = {
    versions: new Map(),
    listReply: json(200, { items: [{ runId: RUN_ID, note: LIST_MARKER }] }),
    uploadReply: undefined,
    accept(request, runId) {
      const sha256 = sha256Hex(zlib.gunzipSync(request.body));
      const known = state.versions.get(sha256);
      if (known !== undefined) return json(200, { runId, sha256, status: "exists", versionNumber: known });
      const versionNumber = state.versions.size + 1;
      state.versions.set(sha256, versionNumber);
      return json(201, { runId, sha256, status: "created", versionNumber });
    },
  };
  const server = await startServer((request, response) => {
    const url = new URL(request.url, "http://service.invalid");
    if (request.method === "GET" && url.pathname === "/api/runs") return state.listReply;
    const versions = /^\/api\/runs\/([^/]+)\/versions$/.exec(url.pathname);
    if (request.method === "POST" && versions) {
      const runId = decodeURIComponent(versions[1]);
      return state.uploadReply === undefined ? state.accept(request, runId) : state.uploadReply(request, runId, response);
    }
    return json(404, { detail: "없다", reason: "notFound" });
  });
  return Object.assign(state, server);
}
