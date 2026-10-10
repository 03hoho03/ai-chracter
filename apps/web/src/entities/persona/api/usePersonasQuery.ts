import { useQuery } from "@tanstack/react-query";

import { personaListQueryOptions } from "./personaListQueryOptions";
import { defaultPersonaName } from "../model/persona";

/** `GET /me/personas` — 목록(생성순)·기본 프로필 id·개수 상한(`maxCount`)을 한 번에 준다. 비로그인이면 401 이라
 * 로그인하지 않은 사람도 보는 화면은 `enabled` 를 세션으로 건다. */
export function usePersonasQuery({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ ...personaListQueryOptions(), enabled });
}

/**
 * 방 없는 화면(홈 큐레이션)에서 작가 글의 `{{user}}` 에 넣을 보는 사람의 이름 — 기본 프로필의 이름이다.
 * 로그인하지 않았거나, 기본 프로필이 없거나, 목록을 아직 모르면 null 이라 대체어로 넘어간다(목록은 앱 전역
 * 캐시라 두 번째 화면부터는 바로 있다).
 */
export function useViewerPersonaName(isLoggedIn: boolean): string | null {
  const { data } = usePersonasQuery({ enabled: isLoggedIn });
  return isLoggedIn ? defaultPersonaName(data) : null;
}

