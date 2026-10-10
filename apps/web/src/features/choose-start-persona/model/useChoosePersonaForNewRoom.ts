import { useQueryClient } from "@tanstack/react-query";

import { personaListQueryOptions, resolveStartPersona, type PersonaList } from "@/entities/persona";

import { FirstPersonaNameModal } from "../ui/FirstPersonaNameModal";

/** 새 방에 실을 프로필. `personaId` 가 undefined 면 서버가 기본(없으면 "선택 없음")으로 시작한다. */
export type NewRoomPersonaChoice = { kind: "chosen"; personaId: string | undefined } | { kind: "cancelled" };

/**
 * 새 대화를 열기 직전에 어느 프로필로 시작할지 정한다. 프로필이 있으면 고른 것(없으면 기본, 기본도 비어 있으면 가장 먼저
 * 만든 것 — `resolveStartPersona`)이고, 하나도 없으면 이름 모달로 첫 프로필을 만든다. 모달을 닫으면 `cancelled` 라
 * 호출부는 방을 만들지 않는다.
 *
 * 목록은 화면이 그려 둔 캐시를 쓰되 없으면 받아 온다 — 로그인하고 돌아와 바로 이어 시작하는 경로는 목록을 그리기 전에
 * 여기 온다. 목록을 못 받으면 막지 않고 서버 기본에 맡긴다(대화 시작이 프로필 조회 하나에 묶이지 않게).
 */
export function useChoosePersonaForNewRoom() {
  const queryClient = useQueryClient();

  return async function choosePersonaForNewRoom(chosenPersonaId?: string): Promise<NewRoomPersonaChoice> {
    let personaList: PersonaList;
    try {
      personaList = await queryClient.ensureQueryData(personaListQueryOptions());
    } catch {
      return { kind: "chosen", personaId: chosenPersonaId };
    }
    if (personaList.items.length > 0) {
      return { kind: "chosen", personaId: resolveStartPersona(personaList, chosenPersonaId)?.id };
    }
    const persona = await FirstPersonaNameModal.call();
    return persona === undefined ? { kind: "cancelled" } : { kind: "chosen", personaId: persona.id };
  };
}
