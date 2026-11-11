// 런 하나의 통째 묶음을 팀이 함께 보는 호스팅 서비스에 올린다. 측정 서버에서 묶음 바이트와 올리기 머리를 받아 출처를 다시 보고,
// gzip 으로 서비스에 보낸 뒤 런 루트의 올리기 기록에 한 줄을 남긴다. 진입점은 `uploadRun.mjs`, 쓰는 법은 `README.md` 의 「올리기」 절.
//
// 서비스 토큰(Client ID·Secret)은 자격 파일에서만 읽고 서비스로 가는 머리 두 개에만 싣는다. 어떤 출력·오류·기록에도 넣지 않는다 —
// Node 의 JSON 파싱·머리 조립 오류 문구는 입력값(이나 그 조각)을 싣기 때문에, 그런 오류는 잡아서 고정 문구로 바꾸고 원래 문구를
// 잇지 않는다.
//
// 종료 코드: 0 올렸고 기록을 남겼다(읽기 시험은 상태 코드를 받았다), 1 거부·실패, 2 인자 오류.

import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { parseArgs } from "node:util";
import zlib from "node:zlib";

import {
  confirmSameRoom,
  DEFAULT_API,
  DEFAULT_ROOT,
  findRun,
  isArchived,
  needsTurnExport,
  Refusal,
  resolveTarget,
} from "./exportTarget.mjs";

const KIB = 1024;
const MIB = 1024 * KIB;
// 서비스의 크기 상한과 같은 값이다. 상한과 같은 크기는 받는다.
const UNCOMPRESSED_LIMIT = 32 * MIB;
const COMPRESSED_LIMIT = 8 * MIB;
const DEFAULT_SERVICE = "https://lab.ddona.site";
const DEFAULT_SERVICE_HOST = new URL(DEFAULT_SERVICE).hostname;
const RECORD_NAME = ".chat-lab-uploads.jsonl";
const CREDENTIALS_LIMIT = 4 * KIB;
const CREDENTIAL_FIELDS = ["clientId", "clientSecret"];
// 머리에 그대로 실을 수 있는 값 — 보이는 ASCII 만. 줄바꿈 같은 글자가 든 값을 머리에 넣으면 Node 가 그 값을 오류 문구에 싣는다.
const HEADER_SAFE_VALUE = /^[\x21-\x7e]{1,512}$/;
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const USAGE = [
  "쓰는 법: uploadRun.mjs <묶음 폴더|드라이버 로그> [--raw] [--exempt-email <주소>]… [--root <런 루트>] [--api <주소>] [--service <주소>] [--credentials <파일>]",
  "        uploadRun.mjs --read-test [--service <주소>] [--credentials <파일>]",
].join("\n");

class UsageError extends Error {}

/**
 * 업로드 CLI 한 번. 성공·읽기 시험 줄은 `io.stdout`, 경고·오류는 `io.stderr` 로만 낸다. 거부·인자 오류는 종료 코드로 돌려주고,
 * 그 밖의 오류는 던진다 — 부르는 쪽(진입점)이 이름·코드만 찍는다.
 * @param {string[]} argv
 * @param {{ env: Record<string, string | undefined>, cwd: string, homedir: string, stdout: { write(chunk: string): unknown }, stderr: { write(chunk: string): unknown } }} io
 * @returns {Promise<0 | 1 | 2>}
 */
export async function runUpload(argv, io) {
  const print = (line) => io.stdout.write(`${line}\n`);
  const warn = (line) => io.stderr.write(`${line}\n`);
  let args;
  try {
    args = parseUploadArgs(argv, io);
  } catch (error) {
    if (!(error instanceof UsageError)) throw error;
    warn(`${error.message}\n${USAGE}`);
    return 2;
  }
  try {
    const credentials = readCredentials(args.credentials);
    if (args.readTest) return await readTest(args.service, credentials, { print, warn });
    return await upload(args, credentials, { print, warn });
  } catch (error) {
    if (!(error instanceof Refusal)) throw error;
    warn(error.message);
    return 1;
  }
}

/**
 * 크기 상한 판정. 압축 크기를 아직 모르면(압축 전) 푼 크기만 본다.
 * @param {{ uncompressedSize: number, compressedSize?: number }} sizes
 * @returns {{ kind: "ok" } | { kind: "tooLarge", part: "uncompressed" | "compressed", message: string }}
 */
export function checkSizes({ uncompressedSize, compressedSize }) {
  if (uncompressedSize > UNCOMPRESSED_LIMIT) {
    return {
      kind: "tooLarge",
      part: "uncompressed",
      message: `묶음이 푼 크기 상한 32MiB 를 넘는다(${formatSize(uncompressedSize)}) — 서비스가 받지 않는다`,
    };
  }
  if (compressedSize !== undefined && compressedSize > COMPRESSED_LIMIT) {
    return {
      kind: "tooLarge",
      part: "compressed",
      message: `압축한 묶음이 상한 8MiB 를 넘는다(${formatSize(compressedSize)}) — 서비스가 받지 않는다`,
    };
  }
  return { kind: "ok" };
}

/**
 * 올리기 기록 자리 — 런 루트 바로 아래 `.chat-lab-uploads.jsonl`. 런 루트가 보관 폴더이거나 그 아래면 거부한다(git 이 추적하는
 * 폴더라 쓰지 않는다). 그 자리에 링크·폴더처럼 일반 파일이 아닌 것이 있어도 거부한다. 런 루트가 git 작업 트리 안이면 그 저장소가
 * 기록 파일을 무시할 때만 받는다 — 무시하지 않으면 런 id·경로·sha 가 든 파일이 커밋될 수 있다. 서비스에 올린 뒤 기록에 못 쓰는
 * 일을 줄이려고 측정 서버에 묻기 전에 판정한다.
 * @param {{ root: string, archiveDirs?: string[] }} input
 * @returns {{ kind: "write", path: string } | { kind: "refused", reason: "archived" | "notFile" | "notIgnored" | "gitUnknown", message: string }}
 */
export function decideRecordPath({ root, archiveDirs }) {
  const file = path.join(root, RECORD_NAME);
  if (isArchived(root, { root, archiveDirs })) {
    return {
      kind: "refused",
      reason: "archived",
      message: `올리기 기록 자리가 archive/ 아래다(${root}) — git 이 추적하는 보관 폴더라 쓰지 않는다`,
    };
  }
  let stat;
  try {
    stat = fs.lstatSync(file);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (stat !== undefined && !stat.isFile()) {
    return { kind: "refused", reason: "notFile", message: `올리기 기록 자리에 일반 파일이 아닌 것이 있다: ${file}` };
  }
  const repository = enclosingRepository(file);
  if (repository === undefined) return { kind: "write", path: file };
  const ignored = gitIgnoresRecord(root);
  if (ignored.kind === "ignored") return { kind: "write", path: file };
  if (ignored.kind === "notIgnored") {
    return {
      kind: "refused",
      reason: "notIgnored",
      message:
        `올리기 기록 자리가 git 작업 트리(${repository}) 안인데 무시 대상이 아니다 — 커밋되면 런 id·경로·sha 가 저장소에 남는다. ` +
        `그 저장소의 .gitignore 에 ${RECORD_NAME} 을 더하거나 저장소 밖 런 루트를 쓴다`,
    };
  }
  return {
    kind: "refused",
    reason: "gitUnknown",
    message: `올리기 기록 자리가 git 작업 트리(${repository}) 안인데 git 으로 무시 여부를 확인하지 못했다(${ignored.why}) — 쓰지 않는다`,
  };
}

/**
 * 그 저장소가 런 루트의 기록 파일을 무시하는가 — git 에 묻는다. 무시 규칙은 폴더마다의 `.gitignore`·저장소의 제외 목록·전역 무시
 * 파일에 흩어져 있고, 이미 추적하는 파일은 규칙과 상관없이 무시되지 않아 색인을 봐야 안다.
 */
function gitIgnoresRecord(root) {
  const env = { ...process.env };
  // git 훅 안에서 돌면 이 값들이 훅을 부른 저장소·색인을 가리켜, 런 루트의 저장소 대신 그쪽을 보게 된다.
  for (const key of ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"]) delete env[key];
  const result = spawnSync("git", ["-C", root, "check-ignore", "-q", "--", RECORD_NAME], {
    env,
    stdio: "ignore",
    timeout: 10_000,
  });
  if (result.error !== undefined) return { kind: "unknown", why: result.error.code ?? result.error.name };
  if (result.status === 0) return { kind: "ignored" };
  if (result.status === 1) return { kind: "notIgnored" };
  return { kind: "unknown", why: result.signal ?? `git 종료 ${result.status}` };
}

function parseUploadArgs(argv, io) {
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      strict: true,
      options: {
        raw: { type: "boolean", default: false },
        "exempt-email": { type: "string", multiple: true },
        root: { type: "string" },
        api: { type: "string" },
        service: { type: "string" },
        credentials: { type: "string" },
        "read-test": { type: "boolean", default: false },
      },
    });
  } catch (error) {
    // parseArgs 의 인자 오류 문구는 플래그 이름만 싣는다. 대상 자리에 붙인 값은 어느 문구에도 싣지 않는다.
    if (typeof error?.code === "string" && error.code.startsWith("ERR_PARSE_ARGS_")) throw new UsageError(error.message);
    throw error;
  }
  const { values, positionals } = parsed;
  const readTest = values["read-test"];
  if (readTest) {
    const uploadOnly =
      positionals.length > 0 ||
      values.raw ||
      values["exempt-email"] !== undefined ||
      values.root !== undefined ||
      values.api !== undefined;
    if (uploadOnly) throw new UsageError("읽기 시험(--read-test)에는 대상·--raw·--exempt-email·--root·--api 를 함께 주지 않는다");
  } else if (positionals.length !== 1) {
    throw new UsageError("대상(묶음 폴더나 드라이버 로그 경로)을 하나만 준다");
  }
  // `pnpm --filter chat-lab …` 은 이 패키지 폴더에서 돌므로, 상대 경로는 명령을 친 자리(`INIT_CWD`) 기준으로 푼다.
  const base = io.env.INIT_CWD ?? io.cwd;
  return {
    readTest,
    base,
    target: positionals[0],
    raw: values.raw,
    exemptEmails: values["exempt-email"] ?? [],
    root: values.root ?? DEFAULT_ROOT,
    api: labAddress(values.api ?? DEFAULT_API),
    service: serviceAddress(values.service ?? DEFAULT_SERVICE),
    credentials: path.resolve(base, values.credentials ?? path.join(io.homedir, ".config", "chat-lab", "service-token.json")),
  };
}

/** 측정 서버는 이 머신에서만 — 루프백 호스트만 받는다. */
function labAddress(value) {
  const url = parseUrl(value);
  if (url === undefined || (url.protocol !== "http:" && url.protocol !== "https:") || !isLoopbackHost(url.hostname)) {
    throw new UsageError("--api 는 루프백 호스트(127.0.0.1·localhost·::1)의 측정 서버 주소만 받는다");
  }
  return value.replace(/\/+$/, "");
}

/**
 * 서비스 주소는 기본 서비스 호스트(https)와 로컬 검증용 루프백 호스트(http 도)만 받는다. 그 밖 호스트는 오타라도 서비스 토큰을
 * 그 호스트로 보내게 되고, http 는 토큰을 평문으로 보낸다.
 */
function serviceAddress(value) {
  const url = parseUrl(value);
  if (url === undefined) throw new UsageError("--service 가 주소 꼴이 아니다(예: https://호스트)");
  // fetch 는 사용자 정보가 든 주소로 요청을 만들지 않는다. 그 실패는 뒤에서 "닿지 못했다"로만 보여 까닭이 가려진다.
  if (url.username !== "" || url.password !== "") throw new UsageError("--service 주소에 사용자 정보(아이디·비밀번호)를 넣지 않는다");
  const web = url.protocol === "https:" || url.protocol === "http:";
  if (web && isLoopbackHost(url.hostname)) return value.replace(/\/+$/, "");
  if (url.protocol !== "https:") {
    throw new UsageError("--service 는 https 주소만 받는다 — 루프백 호스트만 http 를 받는다(서비스 토큰이 평문으로 나가지 않게)");
  }
  if (url.hostname !== DEFAULT_SERVICE_HOST) {
    throw new UsageError(
      `--service 는 기본 서비스 호스트(${DEFAULT_SERVICE_HOST})나 루프백 호스트만 받는다(받은 호스트 ${url.hostname}) — ` +
        "오타로 서비스 토큰이 다른 호스트로 나가지 않게",
    );
  }
  return value.replace(/\/+$/, "");
}

function parseUrl(value) {
  try {
    return new URL(value);
  } catch {
    return undefined;
  }
}

/** `new URL` 은 IPv6 호스트를 대괄호째(`[::1]`) 내놓아 벗기고 견준다. */
function isLoopbackHost(hostname) {
  return LOOPBACK_HOSTS.has(hostname.replace(/^\[(.*)\]$/, "$1"));
}

/**
 * 자격 파일 `{"clientId": …, "clientSecret": …}`. 이 사용자 소유의 0600 일반 파일(링크 아님)이고 git 저장소 밖이어야 한다. 값은
 * 어느 문구에도 싣지 않는다.
 */
function readCredentials(file) {
  let stat;
  try {
    stat = fs.lstatSync(file);
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Refusal(`자격 파일이 없다: ${file} — apps/chat-lab/README.md 「올리기」 절의 명령으로 만든다`);
    }
    throw new Refusal(`자격 파일을 보지 못했다(${error.code ?? error.name}): ${file}`);
  }
  if (stat.isSymbolicLink()) throw new Refusal(`자격 파일이 링크다 — 실제 파일 자리를 --credentials 로 준다: ${file}`);
  if (!stat.isFile()) throw new Refusal(`자격 파일이 일반 파일이 아니다: ${file}`);

  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  } catch (error) {
    if (error.code === "ELOOP") throw new Refusal(`자격 파일이 링크다 — 실제 파일 자리를 --credentials 로 준다: ${file}`);
    throw new Refusal(`자격 파일을 열지 못했다(${error.code ?? error.name}): ${file}`);
  }
  let bytes;
  try {
    // 검사와 열기 사이에 그 자리의 파일이 바뀌었을 수 있어, 연 파일을 다시 본다.
    const opened = fs.fstatSync(fd);
    if (!opened.isFile()) throw new Refusal(`자격 파일이 일반 파일이 아니다: ${file}`);
    if (opened.uid !== process.getuid()) throw new Refusal(`자격 파일의 주인이 이 사용자가 아니다: ${file}`);
    const mode = opened.mode & 0o777;
    if (mode !== 0o600) {
      throw new Refusal(`자격 파일 권한이 0600 이 아니다(지금 ${mode.toString(8).padStart(4, "0")}) — chmod 600 ${file}`);
    }
    // 하드링크는 같은 파일의 다른 이름이라, 아래의 git 저장소 검사가 보지 못하는 자리(저장소 안 등)에 같은 비밀이 있을 수 있다.
    if (opened.nlink !== 1) {
      throw new Refusal(`자격 파일에 하드링크가 걸려 있다(이름 ${opened.nlink}개) — 다른 이름을 지우고 이 자리 하나만 남긴다: ${file}`);
    }
    if (opened.size > CREDENTIALS_LIMIT) throw new Refusal(`자격 파일이 4KiB 를 넘는다: ${file}`);
    bytes = fs.readFileSync(fd);
  } finally {
    fs.closeSync(fd);
  }

  // 링크를 따라간 실제 자리로 본다 — 홈의 설정 폴더를 dotfiles 저장소로 링크해 둔 경우, 그 저장소가 공개면 비밀이 커밋된다.
  let real;
  try {
    real = fs.realpathSync.native(file);
  } catch (error) {
    throw new Refusal(`자격 파일을 보지 못했다(${error.code ?? error.name}): ${file}`);
  }
  const repository = enclosingRepository(real);
  if (repository !== undefined) throw new Refusal(`자격 파일이 git 저장소 안에 있다(${repository}) — 저장소 밖으로 옮긴다`);

  let value;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new Refusal("자격 파일이 JSON 으로 읽히지 않는다");
  }
  const isPlainObject = typeof value === "object" && value !== null && !Array.isArray(value);
  if (!isPlainObject || Object.keys(value).length !== 2 || !CREDENTIAL_FIELDS.every((field) => Object.hasOwn(value, field))) {
    throw new Refusal("자격 파일은 clientId·clientSecret 두 칸만 갖는 JSON 객체여야 한다");
  }
  for (const field of CREDENTIAL_FIELDS) {
    if (typeof value[field] !== "string" || !HEADER_SAFE_VALUE.test(value[field])) {
      throw new Refusal(`자격 파일의 ${field} 값이 비었거나 512자를 넘거나 머리에 실을 수 없는 글자(보이는 ASCII 밖)가 있다`);
    }
  }
  return { clientId: value.clientId, clientSecret: value.clientSecret };
}

/** 그 파일의 조상 폴더 가운데 `.git`(작업 트리·하위 모듈은 파일이다)이 있는 가장 가까운 폴더. 없으면 undefined. */
function enclosingRepository(realFile) {
  let folder = path.dirname(realFile);
  for (;;) {
    try {
      fs.lstatSync(path.join(folder, ".git"));
      return folder;
    } catch {
      // 없다 — 위로 간다.
    }
    const parent = path.dirname(folder);
    if (parent === folder) return undefined;
    folder = parent;
  }
}

function credentialHeaders({ clientId, clientSecret }) {
  return { "CF-Access-Client-Id": clientId, "CF-Access-Client-Secret": clientSecret };
}

/**
 * 같은 자격 파일로 `GET /api/runs` 하나를 보내 상태 코드만 찍는다. 판정은 사람이 한다(서비스 토큰은 사람 경로에서 404 가 정상).
 * 200 이면 본문은 런 목록이라 찍지 않고 버린다.
 */
async function readTest(service, credentials, { print, warn }) {
  let response;
  try {
    response = await fetch(`${service}/api/runs`, { headers: credentialHeaders(credentials), redirect: "manual" });
  } catch (error) {
    warn(`읽기 시험: 서비스에 닿지 못했다(${reachCode(error)})`);
    return 1;
  }
  await response.arrayBuffer().catch(() => undefined);
  print(`읽기 시험: GET /api/runs → ${response.status}`);
  return 0;
}

async function upload(args, credentials, { print, warn }) {
  const { root, relativePosix } = resolveTarget({ base: args.base, root: args.root, target: args.target });
  const record = decideRecordPath({ root });
  if (record.kind === "refused") throw new Refusal(record.message);
  if (args.raw) warn("원문 포함으로 올린다 — 프롬프트·지시문·기억 본문이 서비스에 실려 팀 모두가 본다");

  const item = await findRun(args.api, relativePosix, { log: print });
  const runPath = `${args.api}/runs/${encodeURIComponent(item.runId)}`;
  // sha256 은 측정 서버가 준 이 바이트의 것이다. 다시 직렬화하면 공백·이스케이프·수 표기가 측정 서버와 달라질 수 있다.
  const bytes = await labBundleBytes(`${runPath}/bundle?raw=${args.raw}`);
  const logPath = path.join(root, ...item.path.split("/"));
  const logText = readDriverLog(logPath);
  const bundle = checkBundle(bytes, { item, logText, logPath, raw: args.raw });

  const header = await labUploadHeader(`${runPath}/upload-header`, args.exemptEmails);
  judgeProvenance(header.provenance, logText);
  if (header.provenance.authorInExampleDomain === false) {
    warn("작가가 테스트 계정 밖이다 — 실제 회원의 작품을 테스트 계정으로 플레이한 런이다. 알고 올린다");
  }
  if (header.sourceCommit.dirty === true) warn("커밋하지 않은 변경이 있는 측정 서버가 만든 묶음이다");
  if (needsTurnExport(bundle.detail)) {
    warn(
      "이 판의 원가·토큰이 비어 있다 — 턴 기록을 내보낸 뒤 다시 올린다:\n" +
        `  cd apps/api && uv run python scripts/chat_lab_export_turns.py --run-dir ${path.dirname(logPath)}`,
    );
  }

  const sha256 = crypto.createHash("sha256").update(bytes).digest("hex");
  refuseTooLarge(checkSizes({ uncompressedSize: bytes.length }));
  const compressed = zlib.gzipSync(bytes);
  refuseTooLarge(checkSizes({ uncompressedSize: bytes.length, compressedSize: compressed.length }));

  const reply = await sendToService(`${args.service}/api/runs/${encodeURIComponent(item.runId)}/versions`, {
    compressed,
    header,
    credentials,
  });
  const outcome = describeServiceResponse(reply, { runId: item.runId, sha256 });
  if (outcome.kind === "failed") throw new Refusal(outcome.message);

  const { status, versionNumber } = outcome.result;
  appendUploadRecord(
    record.path,
    {
      at: new Date().toISOString(),
      service: args.service,
      runId: item.runId,
      target: item.path,
      raw: args.raw,
      sha256,
      status,
      versionNumber,
      compressedSize: compressed.length,
      uncompressedSize: bytes.length,
    },
    sha256,
  );
  print(successLine(outcome.result, { raw: args.raw, sha256, compressedSize: compressed.length, uncompressedSize: bytes.length }));
  return 0;
}

async function labBundleBytes(url) {
  let response;
  let bytes;
  try {
    response = await fetch(url, { redirect: "manual" });
    if (response.ok) bytes = Buffer.from(await response.arrayBuffer());
  } catch (error) {
    throw new Refusal(`측정 서버에 닿지 못했다(${url}) — 먼저 띄운다: ${reachCode(error)}`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => undefined);
    throw new Refusal(`측정 서버가 묶음을 거부했다 ${response.status}: ${describeDetail(body?.detail)}`);
  }
  return bytes;
}

function readDriverLog(logPath) {
  try {
    return fs.readFileSync(logPath, "utf8");
  } catch (error) {
    throw new Refusal(`대상 드라이버 로그를 읽지 못했다(${error.code ?? error.name}): ${logPath} — 측정 서버와 같은 --root 인지 본다`);
  }
}

/** 받은 묶음이 고른 런·대상 로그의 방·요청한 원문 여부와 맞고, 계약 판이 있는가. */
function checkBundle(bytes, { item, logText, logPath, raw }) {
  let bundle;
  try {
    bundle = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new Refusal("측정 서버가 준 묶음이 JSON 으로 읽히지 않는다");
  }
  const run = bundle?.detail?.run;
  if (run?.runId !== item.runId) {
    throw new Refusal(`받은 묶음의 런 id 가 고른 런(${item.path})과 다르다 — 측정 서버 응답이 기대한 꼴이 아니다`);
  }
  const same = confirmSameRoom(run.roomId, logText);
  if (same.kind !== "same") {
    throw new Refusal(
      same.kind === "noRoomId"
        ? "받은 묶음에 방 id 가 없어 대상 로그의 런인지 확인할 수 없다"
        : `받은 묶음의 방이 ${logPath} 의 방과 다르다 — 측정 서버를 다른 --root 로 띄웠다면 여기에도 같은 --root 를 준다`,
    );
  }
  if (bundle.raw !== raw) throw new Refusal(`받은 묶음의 원문 여부가 요청과 다르다(요청 ${raw}, 받은 묶음 ${bundle.raw})`);
  if (!Number.isInteger(bundle.contractVersion) || bundle.contractVersion < 1) {
    throw new Refusal("받은 묶음의 계약 판(contractVersion)이 1 이상 정수가 아니다 — 측정 서버를 지금 코드로 다시 띄운다");
  }
  return bundle;
}

async function labUploadHeader(url, exemptEmails) {
  let response;
  let body;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exemptEmails }),
      redirect: "manual",
    });
    body = await response.json().catch(() => undefined);
  } catch (error) {
    throw new Refusal(`측정 서버에 닿지 못했다(${url}) — 먼저 띄운다: ${reachCode(error)}`);
  }
  if (!response.ok) throw new Refusal(`측정 서버가 올리기 머리를 거부했다 ${response.status}: ${describeDetail(body?.detail)}`);
  if (!isObject(body) || !isObject(body.provenance) || !isObject(body.sourceCommit)) {
    throw new Refusal("측정 서버의 올리기 머리가 기대한 꼴({sourceCommit, provenance})이 아니다");
  }
  return body;
}

/**
 * 출처를 로그에서 다시 보고 측정 서버 판정과 견준다. 올리는 것은 로그 판정이 루프백 아님이 아니고, 측정 서버가 통과라 하고, 두
 * 루프백 판정이 같을 때뿐이다. 둘이 어긋나면 닫는 쪽으로 간다 — Node 와 Python 이 같은 주소를 다르게 풀 수 있고, 측정 서버를 다른
 * `--root` 로 띄워 다른 로그를 봤을 수도 있다.
 */
function judgeProvenance(provenance, logText) {
  const fromLog = baseHostIsLocal(driverMeta(logText));
  if (fromLog.local === false) {
    throw new Refusal(`meta 줄 주소가 루프백이 아니다(${fromLog.host}) — 로컬 측정 서버에서 돈 런만 올린다`);
  }
  if (provenance.passed !== true) {
    throw new Refusal(`출처 판정이 실패라 올리지 않는다 — ${provenanceFailures(provenance).join(" / ")}`);
  }
  if (fromLog.local !== provenance.baseLocal) {
    throw new Refusal(
      `출처 판정이 측정 서버와 다르다(로그 ${fromLog.local}, 측정 서버 ${provenance.baseLocal}) — 측정 서버와 같은 --root 인지 본다`,
    );
  }
}

function provenanceFailures(provenance) {
  const reasons = [];
  if (provenance.baseLocal === false) reasons.push("측정 서버가 meta 줄 주소를 루프백이 아니라고 본다 — 로컬 측정 서버에서 돈 런만 올린다");
  if (provenance.roomFound === false) reasons.push("방이 이 DB 에 없다 — 다른 DB 에서 돈 런이다");
  else if (provenance.ownerInExampleDomain === false) reasons.push("방 주인이 테스트 계정이 아니다");
  if (typeof provenance.outsideUsers === "number" && provenance.outsideUsers > 0) {
    reasons.push(`테스트 계정 밖 사용자 ${provenance.outsideUsers}명 — 아는 계정이면 --exempt-email 로 뺀다`);
  }
  if (reasons.length === 0) reasons.push("측정 서버가 실패라 했지만 막은 칸을 알 수 없다");
  return reasons;
}

/** 드라이버 로그에서 처음 `kind: "meta"` 인 줄. 읽히지 않는 줄은 건너뛴다. 없으면 null. */
function driverMeta(logText) {
  for (const line of logText.split("\n")) {
    if (line.trim() === "") continue;
    let value;
    try {
      value = JSON.parse(line);
    } catch {
      continue;
    }
    if (typeof value === "object" && value !== null && value.kind === "meta") return value;
  }
  return null;
}

/** meta 줄의 `base` 호스트가 루프백인가 — 측정 서버의 출처 칸 `baseLocal` 과 같은 규칙. meta 줄이 없으면 판정 없음(null). */
function baseHostIsLocal(meta) {
  if (meta === null) return { local: null };
  if (typeof meta.base !== "string") return { local: false, host: "주소 칸이 문자열이 아니다" };
  const url = parseUrl(meta.base);
  if (url === undefined) return { local: false, host: "주소 꼴이 아니다" };
  return isLoopbackHost(url.hostname) ? { local: true } : { local: false, host: url.hostname || "호스트 없음" };
}

function refuseTooLarge(sizes) {
  if (sizes.kind === "tooLarge") throw new Refusal(sizes.message);
}

async function sendToService(url, { compressed, header, credentials }) {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/gzip",
        "X-Lab-Upload-Header": headerLine(header),
        ...credentialHeaders(credentials),
      },
      body: compressed,
      // 넘김을 따라가면 자격 머리가 넘긴 곳으로 다시 나간다.
      redirect: "manual",
    });
    return { status: response.status, contentType: response.headers.get("content-type") ?? "", text: await response.text() };
  } catch (error) {
    throw new Refusal(`서비스에 닿지 못했다(${reachCode(error)}) — 주소·네트워크를 본다`);
  }
}

/** 올리기 머리를 머리 한 줄로. ASCII 밖 글자는 `\u` 로 적는다 — 머리 값은 바이트 문자열이라 0xFF 를 넘는 글자는 실을 수 없다. */
function headerLine(header) {
  return JSON.stringify(header).replace(
    /[\u007f-￿]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

/**
 * 서비스 응답 → 성공(돌려준 런 id·sha256 이 올린 것과 같은 2xx JSON) 또는 실패 문구. 넘김 주소(`Location`)는 찍지 않는다.
 * @returns {{ kind: "ok", result: { status: unknown, versionNumber: unknown } } | { kind: "failed", message: string }}
 */
function describeServiceResponse({ status, contentType, text }, { runId, sha256 }) {
  const failed = (message) => ({ kind: "failed", message });
  const body = parseJsonBody(contentType, text);
  if (status >= 200 && status < 300) {
    if (!isObject(body)) {
      return failed(`서비스 응답이 JSON 이 아니다(상태 ${status}, content-type ${contentType || "없음"}) — 기록하지 않는다`);
    }
    if (body.runId !== runId) return failed("서비스가 돌려준 런 id 가 올린 런과 다르다 — 기록하지 않는다");
    if (body.sha256 !== sha256) {
      return failed(
        `서비스가 돌려준 sha256 이 올린 묶음과 다르다(로컬 ${shortSha(sha256)}, 서비스 ${shortSha(String(body.sha256))}) — 기록하지 않는다`,
      );
    }
    return { kind: "ok", result: body };
  }
  if (status >= 300 && status < 400) {
    return failed(
      `서비스가 넘겼다(${status}) — Access 가 서비스 토큰을 받지 않고 로그인 화면으로 보낸 것이다. 토큰이 만료됐거나 자격 파일의 Client ID·Secret 이 틀렸을 수 있다 — 토큰을 새로 만들었으면 Access 앱 Service Auth 정책이 새 토큰을 고르는지도 본다.`,
    );
  }
  if (status === 401 || status === 403) {
    return failed(`Access 가 서비스 토큰을 거부했다(${status}) — 토큰이 만료됐거나 자격 파일의 Client ID·Secret 이 틀렸을 수 있다 — 토큰을 새로 만들었으면 Access 앱 Service Auth 정책이 새 토큰을 고르는지도 본다.`);
  }
  if (status === 404) {
    return failed("서비스가 이 토큰의 올리기를 받지 않았다(404) — 토큰의 Client ID 가 서비스의 올리기 허용 목록에 있는지 본다.");
  }
  const reason = typeof body?.reason === "string" ? body.reason : undefined;
  const detail = describeDetail(body?.detail);
  if (status === 413) return failed(`서비스가 크기 상한으로 거부했다(413 ${reason ?? "본문 없음"}): ${detail}`);
  if (status === 422) {
    return failed(reason === undefined ? `요청 꼴이 틀렸다(422): ${detail}` : `서비스가 묶음을 받지 않았다(422 ${reason}): ${detail}`);
  }
  if (status === 503) return failed(`서비스가 지금 받지 못한다(503 ${reason ?? "본문 없음"}) — 잠시 뒤 다시 올린다: ${detail}`);
  return failed(`서비스가 실패했다(${status}, ${reason ?? "본문 없음"})`);
}

function parseJsonBody(contentType, text) {
  if (!contentType.toLowerCase().startsWith("application/json")) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/** 거부 응답의 `detail` — 글이면 그대로, 요청 검증 오류 목록이면 칸(`loc`)과 까닭(`msg`)만. 받은 값(`input`)은 싣지 않는다. */
function describeDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const where = Array.isArray(item?.loc) ? item.loc.join(" ") : "";
        const why = typeof item?.msg === "string" ? item.msg : "";
        return `${where} ${why}`.trim();
      })
      .join(" · ");
  }
  return "(본문 없음)";
}

/** 기록 한 줄을 덧붙인다. 링크를 따라 쓰지 않는다 — 판정 뒤 그 자리가 링크로 바뀌었으면 열기가 실패한다. */
function appendUploadRecord(file, entry, sha256) {
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_APPEND | fs.constants.O_CREAT | fs.constants.O_NOFOLLOW, 0o644);
    fs.writeFileSync(fd, `${JSON.stringify(entry)}\n`);
  } catch (error) {
    throw new Refusal(
      `올렸지만 올리기 기록에 쓰지 못했다(${error.code ?? error.name}) — 판 ${entry.versionNumber} · sha256 ${shortSha(sha256)}`,
    );
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
  }
}

function successLine(result, { raw, sha256, compressedSize, uncompressedSize }) {
  const sha = `sha256 ${shortSha(sha256)}`;
  if (result.status === "created") {
    const sizes = `압축 ${formatSize(compressedSize)} / 푼 ${formatSize(uncompressedSize)}`;
    return `올렸다 — 판 ${result.versionNumber}(새 판) · ${raw ? "원문 포함" : "원문 제외"} · ${sha} · ${sizes}`;
  }
  if (result.status === "exists") return `이미 있다 — 같은 내용의 판 ${result.versionNumber} · ${sha}`;
  if (result.status === "restored") return `되살렸다 — 지웠던 판을 이번 올리기로 다시 살렸다 · 판 ${result.versionNumber} · ${sha}`;
  return `서비스가 받았다(${result.status}) — 판 ${result.versionNumber} · ${sha}`;
}

/** 닿지 못한 까닭은 코드만 적는다. 오류 문구(`message`)는 잇지 않는다 — 어느 문구에 주소·머리 값이 실릴지 다 알 수 없다. */
function reachCode(error) {
  return error?.cause?.code ?? error?.cause?.name ?? error?.name ?? "알 수 없음";
}

function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function shortSha(value) {
  return `${value.slice(0, 12)}…`;
}

function formatSize(bytes) {
  if (bytes >= MIB) return `${(bytes / MIB).toFixed(1)}MiB`;
  if (bytes >= KIB) return `${(bytes / KIB).toFixed(1)}KiB`;
  return `${bytes}B`;
}
