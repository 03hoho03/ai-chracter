/** 사이트 푸터를 그리지 않는 라우트. 채팅방·빌더·이미지 스튜디오는 헤더 아래를 뷰포트 높이로 꽉 채우는
 * 화면이라 그 아래 문서 끝이 없고, `/builder`(타입 선택)는 빌더 셸의 입구라 전역 헤더도 건너뛴다.
 * `/chats`(채팅 목록)는 문서 스크롤 화면이라 `/chat/` 접두사와 갈라 둔다.
 * 소설 화 읽기 화면(`/novels/$novelId/episodes/$chapterId`)은 문서 스크롤이지만 전역 헤더도 숨기는 몰입 뷰어라
 * 본문 끝에 사이트 정보를 붙이지 않는다(화 끝에는 다음 화로 가는 버튼이 온다). 작품 정보 화면(`/novels/$novelId`)은
 * 평범한 문서 화면이라 푸터를 유지한다. */
const NOVEL_EPISODE_PATH = /^\/novels\/[^/]+\/episodes\/[^/]+$/;

export function isSiteFooterHidden(pathname: string): boolean {
  return (
    pathname.startsWith("/chat/") ||
    pathname === "/builder" ||
    pathname.startsWith("/builder/") ||
    pathname === "/studio/images" ||
    pathname.startsWith("/studio/images/") ||
    NOVEL_EPISODE_PATH.test(pathname)
  );
}
