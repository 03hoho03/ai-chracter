import type { QueryClient } from "@tanstack/react-query";

import { personaListQueryOptions, resolveStartPersona, type Persona, type PersonaList } from "@/entities/persona";
import { sessionKeys, type MeResponse } from "@/entities/session";

/** 새 방에 실을 프로필. `personaId` 가 undefined 면 서버가 기본(없으면 "선택 없음")으로 시작한다. */
export type NewRoomPersonaChoice = { kind: "chosen"; personaId: string | undefined } | { kind: "cancelled" };

/**
 * 새 대화를 열기 직전에 어느 프로필로 시작할지 정한다. 프로필이 있으면 고른 것(없으면 기본, 기본도 비어 있으면 가장 먼저
 * 만든 것 — `resolveStartPersona`)이고, 하나도 없으면 `openNameModal` 로 첫 프로필을 만든다. 모달을 닫으면 `cancelled` 라
 * 호출부는 방을 만들지 않는다.
 *
 * - 재동의가 필요한 세션이면 아무것도 묻지 않고 `cancelled` 다 — 화면에는 닫을 수 없는 재동의 모달이 먼저 떠 있고, 서버도
 *   프로필 생성과 방 생성을 거절한다.
 * - 목록은 캐시가 있어도 늘 새로 받는다. 캐시는 로그아웃 전 다른 계정의 것이거나 다른 탭의 변경 전 값일 수 있는데, 그
 *   값으로 판정하면 남의 프로필 id 로 방을 열려다 거절되거나, 프로필이 있는 계정에 이름 모달을 띄워 기본을 덮어쓴다.
 * - 목록을 못 받으면 막지 않고 서버 기본에 맡긴다(대화 시작이 프로필 조회 하나에 묶이지 않게).
 */
export async function choosePersonaForNewRoom(
  queryClient: QueryClient,
  chosenPersonaId: string | undefined,
  openNameModal: () => Promise<Persona | undefined>,
): Promise<NewRoomPersonaChoice> {
  const session = queryClient.getQueryData<MeResponse>(sessionKeys.current());
  if (session?.termsReconsentRequired || session?.privacyReconsentRequired) return { kind: "cancelled" };

  let personaList: PersonaList;
  try {
    personaList = await queryClient.fetchQuery({ ...personaListQueryOptions(), staleTime: 0 });
  } catch {
    return { kind: "chosen", personaId: chosenPersonaId };
  }
  if (personaList.items.length > 0) {
    return { kind: "chosen", personaId: resolveStartPersona(personaList, chosenPersonaId)?.id };
  }
  const persona = await openNameModal();
  return persona === undefined ? { kind: "cancelled" } : { kind: "chosen", personaId: persona.id };
}
