/** 전역 헤더를 그리지 않는 라우트. 빌더(`/builder`, `/builder/$type/$draftId`)는 같은 56px(`h-14`) 자리에 전용
 * 상단바(`BuilderTopBar`)를 두고, 소설 편집 보드(`/novels/$novelId/board`)도 같은 자리에 자기 상단바
 * (`NovelBoardTopBar`)를 둔다. 소설 화 읽기 화면(내 소설 `/novels/$novelId/episodes/$chapterId`, 노벨
 * `/webnovels/$novelId/episodes/$chapterId`)은 몰입 뷰어라 전역 헤더 대신 부를 때만 오는 자기 위·아래 바를 쓴다. 소설
 * 목록과 작품 정보(두 경로 모두)는 평범한 문서 화면이라 헤더를 유지한다. */
const NOVEL_EPISODE_PATH = /^\/(?:web)?novels\/[^/]+\/episodes\/[^/]+$/;
const NOVEL_BOARD_PATH = /^\/novels\/[^/]+\/board$/;

export function isGlobalHeaderHidden(pathname: string): boolean {
  return (
    pathname === "/builder" ||
    pathname.startsWith("/builder/") ||
    NOVEL_EPISODE_PATH.test(pathname) ||
    NOVEL_BOARD_PATH.test(pathname)
  );
}
