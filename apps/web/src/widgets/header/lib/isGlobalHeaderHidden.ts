/** 전역 크롬(헤더와 `lg` 이상의 좌측 패널)을 그리지 않는 라우트. 셸이 헤더와 패널을 이 판정 하나로 함께 가른다 — 둘을
 * 다른 함수로 가르면 헤더 없는 화면에 패널만 남는 화면이 생긴다. 이 화면들은 패널도 그리지 않는다: 빌더 폼 열·보드
 * 캔버스의 폭 실측이 "뷰포트 = 본문 폭"을 전제하고, 화 읽기 화면은 크롬 없는 몰입 뷰어다.
 *
 * 빌더(`/builder`, `/builder/$type/$draftId`)는 같은 57px(안쪽 `h-14` + 경계선) 자리에 전용
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
