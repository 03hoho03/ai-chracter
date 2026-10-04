import { ADMIN_NAV_ITEMS, type AdminNavTo } from "../config/nav";

const IMAGE_GENERATION_VIEW_PATTERN = /^\/users\/[^/]+\/image-generations$/;

/**
 * 지금 화면이 어느 내비 항목에 속하는지 정한다. 사이드바·드로어·상단바 화면명이 모두 이것 하나를 쓴다.
 *
 * 1. `/` 는 모든 경로의 접두사라 정확히 같을 때만 대시보드다.
 * 2. 유저별 생성 이미지 화면은 이미지 생성 목록에서 들어왔다고 URL(`from=image-generations`)이 말하면
 *    이미지 생성 항목이다 — 새 탭·새로고침에서도 같은 판정이 나도록 라우터 state 가 아니라 URL 로 본다.
 *    그 밖에는 경로대로 유저 항목이다.
 * 3. 나머지는 하위 경로(`/reports/$reportId`)까지 접두 일치, 가장 긴 것.
 */
export function resolveActiveNavTo(location: { pathname: string; search: unknown }): AdminNavTo | null {
  const { pathname, search } = location;
  if (pathname === "/") return "/";
  if (IMAGE_GENERATION_VIEW_PATTERN.test(pathname) && isFromImageGenerations(search)) return "/image-generations";

  let matched: AdminNavTo | null = null;
  for (const item of ADMIN_NAV_ITEMS) {
    if (item.to === "/") continue;
    const isMatch = pathname === item.to || pathname.startsWith(`${item.to}/`);
    if (isMatch && (matched === null || item.to.length > matched.length)) matched = item.to;
  }
  return matched;
}

function isFromImageGenerations(search: unknown) {
  return typeof search === "object" && search !== null && "from" in search && search.from === "image-generations";
}
