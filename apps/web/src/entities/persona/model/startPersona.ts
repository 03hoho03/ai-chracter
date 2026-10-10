import type { Persona, PersonaList } from "./persona";

/**
 * 새 대화를 어느 프로필로 시작할지. 고른 것이 목록에 있으면 그것, 없으면(고르지 않았거나 그사이 지워졌으면) 기본, 기본도
 * 없으면 가장 먼저 만든 것이다. 마지막 갈래는 기본이 비어 있는 예전 계정이고, 서버도 방을 만들 때 같은 프로필을 기본으로
 * 올리므로 화면이 미리 보여 준 이름과 방의 이름이 같다. 목록이 생성순이라 첫 항목이 가장 먼저 만든 것이다.
 * 프로필이 없거나 목록을 아직 모르면 null.
 */
export function resolveStartPersona(personaList: PersonaList | undefined, chosenPersonaId?: string): Persona | null {
  if (personaList === undefined) return null;
  const { items, defaultPersonaId } = personaList;
  return (
    items.find((persona) => persona.id === chosenPersonaId) ??
    items.find((persona) => persona.id === defaultPersonaId) ??
    items[0] ??
    null
  );
}
