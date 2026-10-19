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

/** 원작자가 이 작품으로 다른 회원이 소설을 만드는 것을 허용하지 않았다는 403(노벨 정책 스위치가 켜져 있으면 원작자가
 * 탈퇴한 작품도 같다). 채팅 방에서는 방 응답이 미리 알려 주면 메뉴가
 * 막히므로 방을 연 뒤 작가가 허락을 바꾼 경합에서만 온다. 소설 화면에서는 아직 첫 화가 없는 소설의 생성 요청에서도 온다.
 * 계정의 기능 허용(`NOVELIZE_NOT_ALLOWED`)과는 뜻이 달라 판정을 섞지 않는다 — 그 판정은 전역에서 세션을 다시 읽고 "아직 열리지 않은 기능"이라고 말하는데, 이 거절은 계정이 아니라 작품의 설정이다. */
export function isContentNovelizeForbiddenError(error: unknown): boolean {
  return isApiError(error) && error.status === 403 && novelErrorCode(error) === "CONTENT_NOVELIZE_FORBIDDEN";
}

/** 이 작품으로 새 소설·새 화를 만들 수 없다는 문장(`CONTENT_NOVELIZE_FORBIDDEN`, 채팅 방의 `novelCreationBlocked`).
 * 노벨 정책 스위치(가격 응답의 `novelPublicPolicyV2Enabled`)에 따라 막는 이유가 다르다.
 *
 * - 꺼짐: 이유는 원작자의 허락 거부 하나라 그렇게 말한다(스위치가 켜지기 전의 지금 문장).
 * - 켜짐: 원작자가 탈퇴해도 같은 코드·같은 칸으로 막히는데, 서버가 이유를 싣지 않아 어느 쪽인지 모른다. 두 경우에 모두
 *   참인 문장으로 쓴다 — 어느 쪽이든 이용자가 할 수 있는 일은 같다(없다).
 *
 * `room` 은 채팅 방 「소설로 보기」 아래 이유와 그 거절 토스트, `chapter` 는 첫 화가 없는 소설에서 화를 만들 때의 거절이다
 * — 그 화면의 소설은 이미 있어 "새 소설"이 아니라 "새 화"다. 기다려도 풀리지 않는 거절이라 "다시 시도"를 말하지 않는다. */
export function toNovelizeForbiddenCopy(pricing: { novelPublicPolicyV2Enabled?: boolean } | undefined): {
  room: string;
  chapter: string;
} {
  return pricing?.novelPublicPolicyV2Enabled === true
    ? { room: "이 작품으로는 지금 새 소설을 만들 수 없어요.", chapter: "이 작품으로는 지금 새 화를 만들 수 없어요." }
    : {
        room: "원작자가 소설 만들기를 허용하지 않은 작품이에요.",
        chapter: "원작자가 이 작품의 소설 만들기를 허용하지 않아 새 화를 만들 수 없어요.",
      };
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
