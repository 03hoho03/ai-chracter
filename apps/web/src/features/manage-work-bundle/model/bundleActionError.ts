import { isLegalReconsentRequiredError } from "@/entities/legal";
import { WORK_BUNDLE_MAX_COUNT, WORK_BUNDLE_MAX_ITEMS } from "@/entities/work";
import { isApiError } from "@/shared/api/client";

// 서버가 묶음 쓰기에 돌려주는 `detail.code`. 응답에 실리는 실제 식별자다.
const LIMIT_CODE = "WORK_BUNDLE_LIMIT";
const BUNDLE_NOT_FOUND_CODE = "WORK_BUNDLE_NOT_FOUND";
const WORK_NOT_FOUND_CODE = "WORK_NOT_FOUND";

export type WorkBundleAction = "create" | "rename" | "delete" | "addItem" | "removeItem";

export type WorkBundleActionError = {
  kind: "bundleLimit" | "itemLimit" | "bundleGone" | "workGone" | "unknown";
  message: string;
};

/** 실패를 화면에 쓸 문장으로. 같은 409 라도 만들기는 묶음 수, 넣기는 항목 수 한도라 동작을 함께 받는다.
 *
 * 재동의가 필요한 실패면 `null` 이다 — 전역 처리가 세션을 다시 읽어 재동의 모달을 띄우므로 여기서 또 알리지 않는다. */
export function toWorkBundleActionError(error: unknown, action: WorkBundleAction): WorkBundleActionError | null {
  if (isLegalReconsentRequiredError(error)) return null;
  const code = readCode(error);
  if (code === LIMIT_CODE) {
    return action === "create"
      ? { kind: "bundleLimit", message: `묶음은 ${WORK_BUNDLE_MAX_COUNT}개까지 만들 수 있어요. 안 쓰는 묶음을 지운 뒤 다시 만들어 주세요.` }
      : { kind: "itemLimit", message: `한 묶음에는 작품을 ${WORK_BUNDLE_MAX_ITEMS}개까지 넣을 수 있어요.` };
  }
  if (code === BUNDLE_NOT_FOUND_CODE) {
    return { kind: "bundleGone", message: "이 묶음을 찾을 수 없어요. 다른 곳에서 지웠을 수 있어요." };
  }
  if (code === WORK_NOT_FOUND_CODE) {
    return { kind: "workGone", message: "이 작품은 지워졌거나 지금은 묶음에 넣을 수 없어요." };
  }
  return { kind: "unknown", message: `${FAILED_ACTION[action]} 잠시 후 다시 시도해 주세요.` };
}

const FAILED_ACTION: Record<WorkBundleAction, string> = {
  create: "묶음을 만들지 못했어요.",
  rename: "이름을 바꾸지 못했어요.",
  delete: "묶음을 지우지 못했어요.",
  addItem: "묶음에 넣지 못했어요.",
  removeItem: "묶음에서 빼지 못했어요.",
};

function readCode(error: unknown): unknown {
  if (!isApiError(error) || typeof error.detail !== "object") return undefined;
  return error.detail.code;
}
