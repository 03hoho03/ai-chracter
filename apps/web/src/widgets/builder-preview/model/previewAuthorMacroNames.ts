import { defaultPersonaName, type PersonaList } from "@/entities/persona";
import type { PreviewAuthorNameSource } from "@/entities/preview-session";
import { resolveAuthorMacroNames, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

/**
 * 빌더 미리보기에서 작가 글의 `{{user}}`·`{{char}}` 에 넣을 이름. 서버가 미리보기 턴마다 작가의 **현재 기본** 프로필을
 * 쓰므로 화면도 그 이름이 먼저고, 없으면 작품 기본 이름이다(모델이 부른 이름과 화면의 이름이 같다).
 * 목록을 아직 모르면 작품 기본 이름으로 그린다 — 원문 `{{user}}` 를 보이지 않는다.
 *
 * 작품 쪽 값(`source`)은 세션 상태가 들고 있는 것을 넘긴다 — 세션이 있으면 서버가 세션 내내 쓰는 시작 때의 값이고,
 * 세션 전에는 지금 폼 값이다(첫 전송이 그 값으로 세션을 연다).
 */
export function previewAuthorMacroNames(
  source: PreviewAuthorNameSource,
  contentType: "character" | "story",
  personaList: PersonaList | undefined,
): AuthorMacroNames {
  return resolveAuthorMacroNames({
    personaName: defaultPersonaName(personaList),
    defaultUserName: source.defaultUserName,
    contentType,
    contentName: source.contentName,
  });
}
