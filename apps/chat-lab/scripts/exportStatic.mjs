// 런 하나를 측정 서버 없이 `file://` 로 여는 HTML 한 장으로 내보낸다. 웹 빌드(`dist/`)에 측정 서버의 통째 응답
// (`GET /runs/{runId}/bundle`)만 실어, 화면·지표 계산이 측정 서버를 읽는 화면과 갈라지지 않는다. 쓰는 법은 `README.md` 의
// 「정적 HTML 내보내기」 절.
//
// 종료 코드: 0 씀, 1 거부·실패, 2 인자 오류.

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { confirmSameRoom, costGapWarning, decideOutputPath, parseExportArgs, pickRun } from "./exportTarget.mjs";
import { buildStaticHtml } from "./staticHtml.mjs";

const DIST_DIR = fileURLToPath(new URL("../dist/", import.meta.url));

class Refusal extends Error {}

async function main() {
  let args;
  try {
    args = parseExportArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`${error.message}\n쓰는 법: exportStatic.mjs <묶음 폴더|드라이버 로그> [--raw] [--force] [--out <파일>] [--root <런 루트>] [--api <주소>]`);
    return 2;
  }
  // `pnpm --filter chat-lab …` 은 이 패키지 폴더에서 돌므로, 상대 경로는 명령을 친 자리(`INIT_CWD`) 기준으로 푼다.
  const base = process.env.INIT_CWD ?? process.cwd();
  const root = realOrRefuse(path.resolve(base, args.root), "런 루트가 없다");
  const target = realOrRefuse(path.resolve(base, args.target), "대상이 없다");
  const relative = path.relative(root, target);
  if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Refusal(`대상이 런 루트(${root}) 밖이다: ${target}`);
  const relativePosix = relative === "" ? "." : relative.split(path.sep).join("/");

  const indexHtml = readOrRefuse(path.join(DIST_DIR, "index.html"), "웹 빌드가 없다 — 먼저 `pnpm --filter chat-lab exec vite build`");

  const item = await findRun(args.api, relativePosix);
  const bundle = await getJson(`${args.api}/runs/${encodeURIComponent(item.runId)}/bundle?raw=${args.raw}`);
  const logPath = path.join(root, ...item.path.split("/"));
  const same = confirmSameRoom(bundle?.detail?.run?.roomId, fs.readFileSync(logPath, "utf8"));
  if (same.kind !== "same") {
    throw new Refusal(
      same.kind === "noRoomId"
        ? "받은 묶음에 방 id 가 없어 대상 로그의 런인지 확인할 수 없다"
        : `받은 묶음의 방이 ${logPath} 의 방과 다르다 — 측정 서버를 다른 --root 로 띄웠다면 여기에도 같은 --root 를 준다`,
    );
  }

  const decision = decideOutputPath({
    root,
    bundleFolder: path.dirname(logPath),
    logName: path.basename(logPath),
    raw: args.raw,
    force: args.force,
    out: args.out === undefined ? undefined : path.resolve(base, args.out),
  });
  if (decision.kind === "refused") throw new Refusal(`${decision.message} (${decision.reason})`);

  const html = buildStaticHtml({ indexHtml, readAsset: readDistAsset, bundle });
  writeWhole(decision.path, html, { force: args.force });
  console.log(`${decision.path} 에 썼다 (${html.length.toLocaleString("ko-KR")}자, ${args.raw ? "원문 포함" : "원문 제외"})`);
  if (args.raw) console.log("원문 포함 파일이다 — 프롬프트·지시문·기억 본문이 들어 있어 공개 저장소에 커밋하지 않는다.");
  const costWarning = costGapWarning(bundle.detail, path.dirname(logPath));
  if (costWarning !== undefined) console.error(costWarning);
  return 0;
}

async function findRun(api, relativePosix) {
  let picked = pickRun((await getJson(`${api}/runs`)).items, relativePosix);
  if (picked.kind === "none") {
    // 측정 서버는 처음 훑은 결과를 들고 있어, 그 뒤 생긴 묶음은 다시 훑어야 보인다.
    console.log("목록에 없어 측정 서버가 런 루트를 다시 훑는다(실데이터에서 수십 초)…");
    picked = pickRun((await getJson(`${api}/runs?refresh=true`)).items, relativePosix);
  }
  if (picked.kind === "none") throw new Refusal(`측정 서버의 런 목록에 ${relativePosix} 의 묶음이 없다`);
  if (picked.kind === "many") {
    const paths = picked.items.map((candidate) => `  ${candidate.path}`).join("\n");
    throw new Refusal(`그 폴더에 드라이버 로그가 여럿이다 — 로그 경로로 하나를 고른다:\n${paths}`);
  }
  return picked.item;
}

async function getJson(url) {
  let response;
  try {
    response = await fetch(url);
  } catch (error) {
    throw new Refusal(`측정 서버에 닿지 못했다(${url}) — 먼저 띄운다: ${error.cause?.code ?? error.message}`);
  }
  const body = await response.json().catch(() => undefined);
  if (!response.ok) throw new Refusal(`측정 서버가 거부했다 ${response.status}: ${body?.detail ?? "(본문 없음)"}`);
  return body;
}

function readDistAsset(href) {
  const file = path.resolve(DIST_DIR, `.${href}`);
  if (!file.startsWith(DIST_DIR)) throw new Refusal(`dist/ 밖 자산을 가리킨다: ${href}`);
  return readOrRefuse(file, `빌드 자산이 없다: ${href}`);
}

/**
 * 같은 폴더의 임시 파일에 다 쓴 뒤 그 자리로 옮긴다 — 쓰다 끊겨도 반쯤 쓴 HTML 이 남지 않는다. 덮어쓰지 않을 때는 이름 바꾸기 대신
 * 링크를 걸어, 판정 뒤에 생긴 파일도 덮지 않는다(이미 있으면 링크가 실패한다).
 */
function writeWhole(target, text, { force }) {
  const temporary = path.join(path.dirname(target), `.${path.basename(target)}.${process.pid}.tmp`);
  try {
    fs.writeFileSync(temporary, text, { encoding: "utf8", flag: "wx" });
  } catch (error) {
    // 임시 파일이 이미 있으면 이 실행이 만든 것이 아니라 지우지 않는다(같은 프로세스 번호로 앞서 끊긴 실행이 남긴 것이다).
    if (error.code === "EEXIST") throw new Refusal(`임시 파일 ${temporary} 가 이미 있다 — 앞서 끊긴 내보내기가 남긴 것이면 지우고 다시 한다`);
    fs.rmSync(temporary, { force: true });
    throw error;
  }
  try {
    if (force) {
      fs.renameSync(temporary, target);
      return;
    }
    fs.linkSync(temporary, target);
  } catch (error) {
    if (error.code === "EEXIST") throw new Refusal(`${target} 가 그새 생겼다 — 바꾸려면 --force`);
    throw error;
  } finally {
    fs.rmSync(temporary, { force: true });
  }
}

function realOrRefuse(target, message) {
  try {
    return fs.realpathSync.native(target);
  } catch {
    throw new Refusal(`${message}: ${target}`);
  }
}

function readOrRefuse(file, message) {
  try {
    return fs.readFileSync(file, "utf8");
  } catch {
    throw new Refusal(message);
  }
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    console.error(error instanceof Refusal ? error.message : error);
    process.exitCode = 1;
  },
);
