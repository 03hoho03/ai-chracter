import { defaultPersonaName, type PersonaList } from "@/entities/persona";
import type { PreviewStartPayload } from "@/entities/preview-session";
import { resolveAuthorMacroNames, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

/**
 * 빌더 미리보기에서 작가 글의 `{{user}}`·`{{char}}` 에 넣을 이름. 서버가 미리보기 턴마다 작가의 **현재 기본** 프로필을
 * 쓰므로 화면도 그 이름이 먼저고, 없으면 폼에 적힌 작품 기본 이름이다(모델이 부른 이름과 화면의 이름이 같다).
 * 목록을 아직 모르면 작품 기본 이름으로 그린다 — 원문 `{{user}}` 를 보이지 않는다.
 */
export function previewAuthorMacroNames(
  payload: PreviewStartPayload,
  contentType: "character" | "story",
  personaList: PersonaList | undefined,
): AuthorMacroNames {
  return resolveAuthorMacroNames({
    personaName: defaultPersonaName(personaList),
    defaultUserName: payload.defaultUserName,
    contentType,
    contentName: payload.name,
  });
}
