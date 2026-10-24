import { isApiError } from "@/shared/api/client";

/** 잊게 하기(또는 그 전의 함께 지울 장면 수 확인)가 실패했을 때 화면이 할 일.
 * - `gone`: 그 기억이 이미 없다(다른 탭에서 잊었거나 되감기가 지웠다). 목록을 다시 받는다.
 * - `disabled`: 서버 스위치가 꺼졌다. 기억 응답을 다시 받으면 패널이 목록 없는 모양으로 돌아간다.
 * - `message`: 그 밖의 실패. 확인 대화에 문장을 남기고 다시 누를 수 있게 둔다. 재동의 403 은 앱 전역 오류 처리가 모달을
 *   띄우므로 여기서는 일반 문장이다. */
export type ForgetFailure =
  | { kind: "gone"; message: string }
  | { kind: "disabled"; message: string }
  | { kind: "message"; message: string };

const FALLBACK_MESSAGE = {
  forget: "잊게 하지 못했어요. 잠시 후 다시 시도해 주세요.",
  preview: "함께 잊을 장면을 확인하지 못했어요. 다시 확인해 주세요.",
} as const;

export function toForgetFailure(error: unknown, action: "forget" | "preview"): ForgetFailure {
  const code = isApiError(error) && error.status === 404 ? detailCode(error.detail) : undefined;
  if (code === "MEMORY_ITEM_NOT_FOUND") {
    return { kind: "gone", message: "이미 잊었거나 바뀐 기억이에요. 목록을 다시 불러왔어요." };
  }
  if (code === "MEMORY_ITEMS_DISABLED") {
    return { kind: "disabled", message: "지금은 기억을 보거나 잊게 할 수 없어요." };
  }
  return { kind: "message", message: FALLBACK_MESSAGE[action] };
}

/** 함께 지울 장면 수를 묻다 실패했을 때 확인 대화가 할 일. 다시 물어 풀릴 수 있는 실패(연결·서버 오류)만 `retry`로 "다시 확인"을
 * 둔다. 그 기억이 이미 없으면(`gone`) 목록을 다시 받고, 스위치가 꺼졌으면(`disabled`) 기억 응답을 다시 받아 패널을 목록 없는
 * 모양으로 돌린 뒤 둘 다 대화를 닫는다. 그 밖의 거절(`stopped`)은 다시 물어도 같아 실행을 막은 채 닫기만 남긴다. */
export type PreviewFailure =
  | { kind: "gone"; message: string }
  | { kind: "disabled"; message: string }
  | { kind: "retry"; message: string }
  | { kind: "stopped"; message: string };

export function toPreviewFailure(error: unknown): PreviewFailure {
  const failure = toForgetFailure(error, "preview");
  if (failure.kind !== "message") return failure;
  const isTransient = !isApiError(error) || error.status === 0 || error.status >= 500;
  if (isTransient) return { kind: "retry", message: failure.message };
  return { kind: "stopped", message: "지금은 이 사실을 잊게 할 수 없어요. 대화 상자를 닫고 목록을 다시 확인해 주세요." };
}

function detailCode(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || !("code" in detail)) return undefined;
  const { code } = detail;
  return typeof code === "string" ? code : undefined;
}
