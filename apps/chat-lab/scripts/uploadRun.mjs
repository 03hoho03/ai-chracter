// 업로드 CLI 진입점. 흐름은 `uploadFlow.mjs` 의 `runUpload` 이고, 여기서는 종료 코드를 프로세스에 넘기고 예상하지 못한 오류를 받는다.
// 쓰는 법은 `README.md` 의 「올리기」 절.

import os from "node:os";
import process from "node:process";

import { runUpload } from "./uploadFlow.mjs";

try {
  process.exitCode = await runUpload(process.argv.slice(2), {
    env: process.env,
    cwd: process.cwd(),
    homedir: os.homedir(),
    stdout: process.stdout,
    stderr: process.stderr,
  });
} catch (error) {
  // 이름과 코드만 찍는다. 문구·스택·cause 는 싣지 않는다 — 머리·자격 값이 어느 오류 문구에 실릴지 모두 알 수 없다.
  process.stderr.write(`예상하지 못한 오류로 멈췄다(${error?.name ?? typeof error} ${error?.code ?? "코드 없음"})\n`);
  process.exitCode = 1;
}
