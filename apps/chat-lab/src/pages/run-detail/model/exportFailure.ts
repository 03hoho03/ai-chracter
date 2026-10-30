import type { components } from "@/shared/api/generated";
import { isServerUnreachable } from "@/shared/api/isServerUnreachable";
import { readLabError } from "@/shared/api/readLabError";

type LabErrorReason = components["schemas"]["LabError"]["reason"];
type RefusalReason = Exclude<LabErrorReason, "exists">;

/**
 * 턴 기록 내보내기가 실패했을 때 화면이 할 일.
 * - `confirmOverwrite`: 파일이 이미 있다 — 덮어쓸지 묻는다. 강제로 다시 보내자고 권하는 것은 이 경우뿐이다(링크·폴더가 그 자리에
 *   있으면 강제로도 못 쓴다).
 * - `refused`: 측정 서버가 거부했다 — 서버 문장(`detail`)을 그대로 보이고 거부 종류마다 할 일을 한 줄 붙인다.
 * - `unreachable`: 측정 서버에 닿지 못했다.
 * - `unknown`: 측정 서버의 거부 본문이 아니다(요청 검증 오류 등) — 오류 글을 그대로.
 */
export type ExportFailure =
  | { kind: "confirmOverwrite"; detail: string }
  | { kind: "refused"; reason: RefusalReason; detail: string; hint: string }
  | { kind: "unreachable" }
  | { kind: "unknown"; message: string };

/** 거부 종류마다 이어서 할 일. 서버 문장은 무엇이 막혔는지를, 이 문장은 그다음 무엇을 하면 되는지를 말한다. */
const EXPORT_HINTS = {
  notFound: "목록에서 새로 훑은 뒤 런을 다시 연다 — 서버가 훑은 뒤 묶음이 옮겨졌거나 지워졌다.",
  unsupported: "옛 형식 묶음이라 턴 기록을 잇지 않는다 — 내보낼 수 없다.",
  openFailed: "묶음 파일을 열지 못했다 — 드라이버 로그가 깨지지 않았는지 본다.",
  archived: "archive/ 는 저장소가 추적하는 보관 폴더라 쓰지 않는다 — 묶음을 보관 폴더 밖에 복사해 거기서 내보낸다.",
  notFile: "그 자리의 링크·폴더를 치운 뒤 다시 내보낸다 — 강제로도 그 위에는 쓰지 않는다.",
  noRoom: "이 방이 로컬 DB 에 없다 — 측정 서버를 --database-url 로 그 런을 돈 DB 에 붙여 다시 띄운다.",
  noRows: "DB 에 방은 있지만 턴 기록이 없다 — 그 런을 돈 DB 인지, 방을 초기화하지 않았는지 본다.",
  multipleRooms: "폴더 하나에 방이 여럿이다 — 턴 기록 파일은 폴더에 하나라 드라이버 로그를 방마다 다른 폴더로 나눈다.",
  dbUnavailable: "측정 서버가 DB 를 쓸 수 없다 — 로컬 DB 가 떠 있는지 보고, 서버를 --database-url 과 함께 다시 띄운다.",
  notJson: "요청 본문 형식이 맞지 않았다 — 이 화면과 측정 서버의 판이 같은지 본다.",
} as const satisfies Record<RefusalReason, string>;

export function describeExportFailure(error: unknown): ExportFailure {
  if (isServerUnreachable(error)) return { kind: "unreachable" };
  const labError = readLabError(error);
  if (labError === undefined) {
    return { kind: "unknown", message: error instanceof Error ? error.message : "측정 서버가 알 수 없는 모양으로 실패했다." };
  }
  if (labError.reason === "exists") return { kind: "confirmOverwrite", detail: labError.detail };
  return { kind: "refused", reason: labError.reason, detail: labError.detail, hint: EXPORT_HINTS[labError.reason] };
}
