import type { RegisteredRouter, RouteById } from "@tanstack/react-router";
import { atom, useAtomValue, useSetAtom } from "jotai";
import { useCallback, useEffect } from "react";

/** "목록으로"가 돌아갈 목록들. 키는 라우트 id 다(목록을 `.index.tsx` 로 두는 규약이라 끝에 슬래시가 붙는다). */
export type ListRouteId =
  | "/contents/"
  | "/novels/"
  | "/users/"
  | "/reports/"
  | "/inquiries/"
  | "/notices/"
  | "/image-generations/";

/** 그 목록 라우트가 검증한 search 타입. 라우터 등록(`Register`)에서 읽는 타입이라 shared 가 app 을 import 하지 않는다. */
export type ListSearch<Id extends ListRouteId> = RouteById<RegisteredRouter["routeTree"], Id>["types"]["fullSearchSchema"];

type ListSearchMemory = { [Id in ListRouteId]?: ListSearch<Id> };

/**
 * 목록마다 마지막으로 본 search(필터·검색어·페이지). 상세의 "목록으로"가 이것을 실어 보내 같은 목록으로 돌아간다 —
 * 대시보드·다른 상세의 링크로 상세에 들어왔어도 그렇다. 새로고침하면 비는 메모리 기억이고, 브라우저 뒤로가기는 URL
 * 이 이미 보존하므로 여기 기대지 않는다.
 */
const listSearchMemoryAtom = atom<ListSearchMemory>({});

/**
 * 목록 라우트 컴포넌트가 부른다: 지금 search 를 그 목록의 마지막 값으로 적는다. 라우터가 들고 있는 값을 다른 저장소로
 * 옮겨 적는 동기화라 효과로 한다.
 */
export function useRememberListSearch<Id extends ListRouteId>(id: Id, search: ListSearch<Id>) {
  const setMemory = useSetAtom(listSearchMemoryAtom);
  useEffect(() => {
    setMemory((memory) => ({ ...memory, [id]: search }));
  }, [id, search, setMemory]);
}

/** "목록으로"가 읽는다. 아직 그 목록을 연 적이 없으면 `undefined` — 링크는 search 없이 기본 목록으로 간다. */
export function useRememberedListSearch<Id extends ListRouteId>(id: Id): ListSearch<Id> | undefined {
  return useAtomValue(listSearchMemoryAtom)[id];
}

/**
 * 로그인·로그아웃이 성공하면 부른다. 로그아웃은 새로고침 없는 화면 이동이라, 같은 탭에서 다른 관리자가 로그인하면 앞
 * 사람의 마지막 검색(찾아본 유저 이메일 등)이 "목록으로"에 실려 나온다. 세션이 바뀌는 길은 이 둘뿐이다(세션이 만료돼도
 * 다시 들어오려면 로그인을 거친다).
 */
export function useClearListSearchMemory() {
  const setMemory = useSetAtom(listSearchMemoryAtom);
  return useCallback(() => setMemory({}), [setMemory]);
}
