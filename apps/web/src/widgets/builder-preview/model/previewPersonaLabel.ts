import type { PersonaList } from "@/entities/persona";

/** 빌더 미리보기 헤더의 한 줄 안내 — 이번 턴에 들어갈 대화 프로필. BE는 미리보기 턴마다 작가의 **현재 기본**
 * 프로필을 읽으므로(`_preview_persona_dependency`, UP-10) 목록 쿼리의 `defaultPersonaId`가 곧 그 값이다.
 *
 * `undefined` = 숨긴다. 목록을 모르거나(로딩·에러) 응답이 어긋났을 때 "없이 진행"이라고 말하면 거짓일 수
 * 있어서다(persona-progress.md S8 ⚪-3). */
export function previewPersonaLabel(personaList: PersonaList | undefined): string | undefined {
  if (!personaList) return undefined;
  if (personaList.defaultPersonaId === null) return "대화 프로필 없이 진행";
  const persona = personaList.items.find((item) => item.id === personaList.defaultPersonaId);
  return persona ? `대화 프로필: ${persona.name}` : undefined;
}
