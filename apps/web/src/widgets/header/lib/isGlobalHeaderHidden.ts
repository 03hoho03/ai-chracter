/** 전역 헤더를 그리지 않는 라우트. 빌더(`/builder`, `/builder/$type/$draftId`)는 같은 56px(`h-14`) 자리에 전용
 * 상단바(`BuilderTopBar`)를 둔다. 소설 화 읽기 화면(`/novels/$novelId/episodes/$chapterId`)은 몰입 뷰어라 정지
 * 상태에 크롬이 없고, 본문을 탭할 때만 자기 위·아래 바를 띄운다. 소설 목록(`/novels`)과 작품 정보(`/novels/$novelId`)는
 * 평범한 문서 화면이라 헤더를 유지한다. */
const NOVEL_EPISODE_PATH = /^\/novels\/[^/]+\/episodes\/[^/]+$/;

export function isGlobalHeaderHidden(pathname: string): boolean {
  return pathname === "/builder" || pathname.startsWith("/builder/") || NOVEL_EPISODE_PATH.test(pathname);
}
