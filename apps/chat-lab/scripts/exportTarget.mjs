// 정적 HTML 내보내기의 인자·대상 런·출력 자리 판정. 측정 서버를 부르고 파일을 쓰는 것은 `exportStatic.mjs` 가 한다.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

/** 측정 서버의 기본 런 루트와 같은 자리. 서버를 다른 `--root` 로 띄웠으면 여기에도 같은 값을 준다. */
export const DEFAULT_ROOT = fileURLToPath(new URL("../../api/probe-runs", import.meta.url));
/** 측정 서버의 기본 주소(`src/shared/api/client.ts` 의 기본값과 같은 포트). */
export const DEFAULT_API = "http://127.0.0.1:8791";
// 저장소가 추적하는 측정 기록 보관 폴더. 런 루트를 바꿔도 늘 거부한다 — 측정 서버의 턴 기록 내보내기와 같은 규칙이다.
const REPO_ARCHIVE = fileURLToPath(new URL("../../api/probe-runs/archive", import.meta.url));
const ARCHIVE_DIR_NAME = "archive";

/**
 * 명령줄 인자. 대상(묶음 폴더나 드라이버 로그) 하나와 플래그. 원문 포함(`--raw`)·덮어쓰기(`--force`)는 이름 붙은 플래그로만
 * 켜고, 모르는 플래그는 던진다 — 철자가 틀린 플래그가 조용히 무시되면 뜻과 다른 파일이 나온다.
 * @param {string[]} argv
 * @returns {{ target: string, raw: boolean, force: boolean, out: string | undefined, root: string, api: string }}
 */
export function parseExportArgs(argv) {
  const { values, positionals } = parseArgs({
    args: argv,
    allowPositionals: true,
    strict: true,
    options: {
      raw: { type: "boolean", default: false },
      force: { type: "boolean", default: false },
      out: { type: "string" },
      root: { type: "string" },
      api: { type: "string" },
    },
  });
  if (positionals.length !== 1) throw new Error("대상(묶음 폴더나 드라이버 로그 경로)을 하나만 준다");
  return {
    target: positionals[0],
    raw: values.raw,
    force: values.force,
    out: values.out,
    root: values.root ?? DEFAULT_ROOT,
    api: values.api ?? DEFAULT_API,
  };
}

/**
 * 런 목록에서 대상 런. `relativeTarget` 은 런 루트 기준 POSIX 경로(루트 자신은 `.`)다. 드라이버 로그 경로면 그 묶음이고, 폴더면
 * 그 폴더 바로 아래 드라이버 로그의 묶음이다. 폴더에 로그가 둘 이상이면 고르지 않는다.
 * @template {{ path: string }} T
 * @param {T[]} items
 * @param {string} relativeTarget
 * @returns {{ kind: "one", item: T } | { kind: "many", items: T[] } | { kind: "none" }}
 */
export function pickRun(items, relativeTarget) {
  const matches = items.filter((item) => item.path === relativeTarget || path.posix.dirname(item.path) === relativeTarget);
  if (matches.length === 0) return { kind: "none" };
  if (matches.length === 1) return { kind: "one", item: matches[0] };
  return { kind: "many", items: matches };
}

/**
 * 기본 파일 이름 — 드라이버 로그 이름을 따라 한 폴더의 여러 런이 서로 덮지 않고, 원문을 담은 파일은 `.raw` 가 붙어 이름만 보고도
 * 원문 없는 파일과 갈린다.
 * @param {string} logName
 * @param {boolean} raw
 */
export function defaultOutputName(logName, raw) {
  return `${logName.replace(/\.jsonl$/, "")}${raw ? ".raw" : ""}.html`;
}

/**
 * 받은 묶음이 대상 드라이버 로그의 런인가. 측정 서버와 이 스크립트의 런 루트가 다르면 같은 상대 경로가 다른 런을 가리켜, 다른
 * 런의 데이터를 고른 폴더에 쓰게 된다. 글자 포함이 아니라 줄마다 방 id 칸을 읽는다 — 응답 글에 다른 방 id 가 적혀 있을 수 있다.
 * 읽지 못하는 줄(기록 중에 잘린 끝 줄 등)은 건너뛴다.
 *
 * 받은 묶음에 방 id 가 없으면 확인할 수 없음이고, 부르는 쪽은 쓰지 않는다. 측정 서버가 여는 묶음에는 방 id 가 늘 있어서(열지 않는
 * 옛 형식은 묶음 요청이 거부된다), 없다는 것은 응답이 기대한 꼴이 아니라는 뜻이다.
 * @param {unknown} roomId
 * @param {string} logText
 * @returns {{ kind: "same" } | { kind: "different", logRoomIds: string[] } | { kind: "noRoomId" }}
 */
export function confirmSameRoom(roomId, logText) {
  if (typeof roomId !== "string" || roomId === "") return { kind: "noRoomId" };
  const rooms = new Set();
  for (const line of logText.split("\n")) {
    if (line.trim() === "") continue;
    let value;
    try {
      value = JSON.parse(line);
    } catch {
      continue;
    }
    if (typeof value === "object" && value !== null && typeof value.roomId === "string") rooms.add(value.roomId);
  }
  return rooms.size === 1 && rooms.has(roomId) ? { kind: "same" } : { kind: "different", logRoomIds: [...rooms] };
}

/**
 * 턴 기록 파일 없이 내보내는 런이면 알릴 문장, 아니면 undefined. 그 파일의 원가·토큰 칸은 "내보내기 필요"로 남는데, 파일을 받은
 * 사람은 턴 기록을 내보낼 수 없다 — 내보내는 사람이 먼저 턴 기록을 내보내고 다시 내보내야 채워진다. 측정 서버는 쓸 턴 기록이 없을
 * 때와 행을 잇지 않는 `assistantMessageId` 이전 형식일 때만 원가를 비우고, 이전 형식은 턴 기록을 내보내도 채워지지 않아 알리지
 * 않는다.
 * @param {{ cost: unknown, run: { format: string } }} detail
 * @param {string} bundleFolder
 * @returns {string | undefined}
 */
export function costGapWarning(detail, bundleFolder) {
  if (detail.cost !== null || detail.run.format === "preMessageId") return undefined;
  return (
    "턴 기록 파일이 없어 이 파일의 원가·토큰이 비어 있다 — 먼저 턴 기록을 내보낸 뒤 다시 내보낸다:\n" +
    `  cd apps/api && uv run python scripts/chat_lab_export_turns.py --run-dir ${bundleFolder}`
  );
}

/**
 * 쓸 자리. 거부하는 것:
 * - `archived`: 그 폴더나 조상이 보관 폴더(런 루트의 `archive/`, 저장소의 보관 폴더)다. git 이 추적하는 폴더라 쓰면 대화 원문이 든
 *   파일이 공개 저장소에 커밋될 수 있다. 경로 글자가 아니라 장치·inode 로 같은 폴더인지 본다 — 링크나 다른 대소문자로 닿아도 막는다.
 * - `outsideRoot`: 그 폴더가 런 루트 밖이다(gitignore 밖의 추적 경로에 쓰지 않는다). 다른 곳에 두려면 쓴 뒤 복사한다.
 * - `noFolder`: 출력 폴더가 없다. 만들지 않는다.
 * - `exists`: 파일이 이미 있다 — 손으로 고친 보고서일 수 있어 `force` 일 때만 바꾼다.
 * - `notFile`: 그 자리에 링크·폴더 등 일반 파일이 아닌 것이 있다. 강제여도 쓰지 않는다.
 * @param {{ root: string, bundleFolder: string, logName: string, raw: boolean, force: boolean, out?: string, archiveDirs?: string[] }} input
 * @returns {{ kind: "write", path: string } | { kind: "refused", reason: "archived" | "outsideRoot" | "noFolder" | "exists" | "notFile", message: string }}
 */
export function decideOutputPath({ root, bundleFolder, logName, raw, force, out, archiveDirs }) {
  const requested = out === undefined ? path.join(bundleFolder, defaultOutputName(logName, raw)) : path.resolve(out);
  let folder;
  try {
    folder = fs.realpathSync.native(path.dirname(requested));
  } catch {
    return refused("noFolder", `출력 폴더가 없다: ${path.dirname(requested)}`);
  }
  if (!fs.statSync(folder).isDirectory()) return refused("noFolder", `출력 폴더가 폴더가 아니다: ${folder}`);
  const chain = ancestry(folder).map(identity);
  const archives = new Set(
    (archiveDirs ?? [path.join(root, ARCHIVE_DIR_NAME), REPO_ARCHIVE]).map(identity).filter((id) => id !== undefined),
  );
  if (chain.some((id) => id !== undefined && archives.has(id))) {
    return refused("archived", `${folder}: ${ARCHIVE_DIR_NAME}/ 아래에는 쓰지 않는다 — git 이 추적하는 보관 폴더다`);
  }
  const rootId = identity(root);
  if (rootId === undefined || !chain.includes(rootId)) {
    return refused("outsideRoot", `${folder}: 런 루트(${root}) 밖에는 쓰지 않는다 — 다른 곳에 두려면 쓴 뒤 복사한다`);
  }
  const target = path.join(folder, path.basename(requested));
  let stat;
  try {
    stat = fs.lstatSync(target);
  } catch (error) {
    if (error.code === "ENOENT") return { kind: "write", path: target };
    throw error;
  }
  if (!stat.isFile()) return refused("notFile", `${target}: 그 자리에 일반 파일이 아닌 것이 있다`);
  if (!force) return refused("exists", `${target} 가 이미 있다 — 바꾸려면 --force`);
  return { kind: "write", path: target };
}

function refused(reason, message) {
  return { kind: "refused", reason, message };
}

/** 그 폴더와 조상 전부(루트 `/` 까지). */
function ancestry(folder) {
  const chain = [folder];
  while (path.dirname(chain[chain.length - 1]) !== chain[chain.length - 1]) chain.push(path.dirname(chain[chain.length - 1]));
  return chain;
}

/** 같은 폴더인지 견줄 열쇠(장치·inode). 없거나 못 읽으면 undefined. */
function identity(target) {
  try {
    // inode 는 2^53 을 넘을 수 있어 bigint 로 읽는다.
    const stat = fs.statSync(target, { bigint: true });
    return `${stat.dev}:${stat.ino}`;
  } catch {
    return undefined;
  }
}
