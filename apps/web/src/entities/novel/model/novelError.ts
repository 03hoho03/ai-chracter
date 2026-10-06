import { isApiError } from "@/shared/api/client";

/** 소설 쪽 오류 본문은 `{"detail": {"code": ...}}` 객체다. 방 소유권 오류와 정지 403 은 `detail` 이 문자열이라
 * 객체인지부터 본다(요청 검증 422 의 배열은 응답 인터셉터가 `fields` 로 펴고 `detail` 에 남기지 않는다). */
function novelErrorCode(error: unknown): string | undefined {
  if (!isApiError(error) || !error.detail || typeof error.detail !== "object") return undefined;
  const { code } = error.detail;
  return typeof code === "string" ? code : undefined;
}

/** 소설화가 이 계정에 열려 있지 않다는 403. 기능 스위치가 꺼졌을 때·허용을 회수했을 때·허용 명단에서 빠졌을 때
 * 모두 같은 코드라 화면도 하나로 다룬다. */
export function isNovelizeNotAllowedError(error: unknown): boolean {
  return isApiError(error) && error.status === 403 && novelErrorCode(error) === "NOVELIZE_NOT_ALLOWED";
}

export type NovelLoadFailure = "locked" | "missing" | "failed";

/** 소설 상세를 못 읽었을 때 화면이 어느 안내를 그릴지. 없는 소설과 남의 소설은 이용자에게 같은 일이라("열 수 있는
 * 소설이 아니다") 하나로 접는다. 그 밖(네트워크·5xx)은 다시 시도할 수 있는 실패다. */
export function toNovelLoadFailure(error: unknown): NovelLoadFailure {
  if (isNovelizeNotAllowedError(error)) return "locked";
  const code = novelErrorCode(error);
  if (code === "NOVEL_NOT_FOUND" || code === "NOVEL_FORBIDDEN") return "missing";
  return "failed";
}

/** 소설 쪽 오류가 이 코드인가. 같은 거절이라도 화면이 다르게 받아야 하는 자리(이미 지워진 것을 지우려 한 404 는
 * 지운 것과 같다)에서 쓴다. */
export function hasNovelErrorCode(error: unknown, code: string): boolean {
  return novelErrorCode(error) === code;
}
