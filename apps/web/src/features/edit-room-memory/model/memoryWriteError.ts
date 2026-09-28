import { isApiError } from "@/shared/api/client";

export const MEMORY_CONFLICT_MESSAGE = "그사이 기억이 갱신됐어요";
export const MEMORY_SUMMARY_NOT_READY_MESSAGE = "아직 고칠 수 있는 요약이 없어요.";
export const MEMORY_NOTHING_TO_REVERT_MESSAGE = "되돌릴 수 있는 내용이 없어요.";
export const INVALID_MEMORY_INPUT_MESSAGE = "입력한 내용을 다시 확인해 주세요.";
export const GENERIC_MEMORY_ERROR_MESSAGE = "저장하지 못했어요. 잠시 후 다시 시도해 주세요.";

/** 기억 쓰기 실패의 두 갈래. `stale`은 폼을 연 뒤 서버의 기억이 바뀌었다는 뜻이라 문구만이 아니라 다음
 * 행동("다시 불러오기")이 다르다 — 그래서 문자열이 아니라 판별값으로 돌려준다.
 *
 * 409의 세 코드는 BE 기억 API가 `detail.code`로 준다. 요약이 없어서(첫 접기 전)·되돌릴 것이 없어서의
 * 409도 "화면이 서버보다 낡았다"는 뜻이라(화면은 요약이나 되돌리기 버튼을 보여 주고 있었다) 다시
 * 불러오면 풀린다 — 그래서 셋 다 `stale`이고 문구만 다르다. 422는 pydantic 원문이라 노출하지 않는다.
 * 재동의 403은 앱 전역 뮤테이션 오류 처리가 모달을 띄우므로 여기서는 일반 문구로 둔다. */
export type MemoryWriteError = { kind: "stale"; message: string } | { kind: "message"; message: string };

const STALE_MESSAGE_BY_CODE: Record<string, string> = {
  MEMORY_VERSION_CONFLICT: MEMORY_CONFLICT_MESSAGE,
  MEMORY_SUMMARY_NOT_READY: MEMORY_SUMMARY_NOT_READY_MESSAGE,
  MEMORY_NOTHING_TO_REVERT: MEMORY_NOTHING_TO_REVERT_MESSAGE,
};

export function toMemoryWriteError(error: unknown): MemoryWriteError {
  if (!isApiError(error)) return { kind: "message", message: GENERIC_MEMORY_ERROR_MESSAGE };
  if (error.status === 409) {
    const code = error.detail && typeof error.detail === "object" ? error.detail.code : undefined;
    const message = typeof code === "string" ? STALE_MESSAGE_BY_CODE[code] : undefined;
    return { kind: "stale", message: message ?? MEMORY_CONFLICT_MESSAGE };
  }
  if (error.status === 422) return { kind: "message", message: INVALID_MEMORY_INPUT_MESSAGE };
  return { kind: "message", message: GENERIC_MEMORY_ERROR_MESSAGE };
}
