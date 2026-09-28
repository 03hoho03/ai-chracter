import { isApiError } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";

export type ReferenceImageError = "not_found" | "disabled";

/** 생성 POST가 참조 이미지 때문에 거절됐는지 가른다. 서버는 두 경우를 고정 `detail` 문자열로
 * 알리는데, 404·400은 다른 이유(없는 경로·지원하지 않는 비율 등)로도 오므로 **상태와 문구를 짝으로**
 * 본다 — 한쪽만 보면 참조와 무관한 실패에서 참조를 비우거나, 참조 실패를 일반 실패로 삼킨다.
 * 문자열은 사용자에게 보이지 않는다(판별에만 쓰고 문구는 아래에서 한국어로 짓는다). */
export function getReferenceImageError(error: unknown): ReferenceImageError | undefined {
  if (!isApiError(error)) return undefined;
  if (error.status === 404 && error.detail === "reference image not found") return "not_found";
  if (error.status === 400 && error.detail === "reference image disabled") return "disabled";
  return undefined;
}

/** 두 경우 모두 참조를 비운다 — 비우지 않으면 다음 제출이 같은 오류로 되풀이된다. `not_found`는
 * 고른 이미지가 그 사이 지워졌거나(같은 화면의 보관함에서 지울 수 있다) 더는 쓸 수 없는 경우라 다시
 * 고르게 하고, `disabled`는 서버가 참조를 껐다는 뜻이라 다시 고르라고 하지 않는다. */
export function formatReferenceImageErrorMessage(error: ReferenceImageError): string {
  switch (error) {
    case "not_found":
      return "참조 이미지를 찾을 수 없어요. 다시 골라 주세요.";
    case "disabled":
      return "지금은 참조 이미지를 쓸 수 없어요.";
    default:
      return assertNever(error);
  }
}
