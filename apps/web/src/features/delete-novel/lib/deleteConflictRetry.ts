import { isApiError } from "@/shared/api/client";

/** 소설·마지막 묶음 삭제를 보내되, 그사이 새 소장자가 생겨 서버가 409 `NOVEL_DELETE_CONFLICT` 로 돌려보내면 한 번만 다시
 * 보낸다. 서버는 삭제 직전에 소장자들을 잠그는데, 고른 뒤 잠그기 전에 새로 산 사람이 보이면 순서를 지키려고 지우지 않고
 * 돌려보낸다 — 다시 보내면 그 사람까지 함께 잠가 지우고 환급한다. 두 번째도 같은 409 면 그대로 던진다(계속 경합이면
 * 사람이 다시 누르게 둔다). */
export async function withDeleteConflictRetry<T>(send: () => Promise<T>): Promise<T> {
  try {
    return await send();
  } catch (error) {
    if (!isDeleteConflict(error)) throw error;
    return send();
  }
}

function isDeleteConflict(error: unknown): boolean {
  return (
    isApiError(error) &&
    error.status === 409 &&
    typeof error.detail === "object" &&
    error.detail !== null &&
    error.detail.code === "NOVEL_DELETE_CONFLICT"
  );
}
