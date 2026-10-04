import { resolveAuthorMacroNames } from "@/shared/lib/text/authorMacros";

/**
 * 채팅 화면 예시(시드 원문)의 `{{user}}` 에 넣는 이름. 예시는 "플레이어가 보게 될 화면"이라 매크로를 글자로 두지 않고
 * 바꿔 보인다 — 읽는 사람의 프로필이 아니라 아무 프로필도 없는 플레이어 기준이라 대체어다. 빌더 칸 목업은 작가가 쓰는
 * 원문 그대로 둔다. 예시 원본(시드)에 작품 기본 이름이나 `{{char}}` 를 쓰게 되면 여기에 그 값을 넣어야 글자로 새지 않는다.
 */
export const GUIDE_CHAT_MACRO_NAMES = resolveAuthorMacroNames({
  personaName: null,
  defaultUserName: null,
  contentType: "story",
  contentName: null,
});
