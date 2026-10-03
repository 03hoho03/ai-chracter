/** 사이트 푸터를 그리지 않는 라우트. 채팅방·빌더·이미지 스튜디오는 헤더 아래를 뷰포트 높이로 꽉 채우는
 * 화면이라 그 아래 문서 끝이 없고, `/builder`(타입 선택)는 빌더 셸의 입구라 전역 헤더도 건너뛴다.
 * `/chats`(채팅 목록)는 문서 스크롤 화면이라 `/chat/` 접두사와 갈라 둔다. */
export function isSiteFooterHidden(pathname: string): boolean {
  return (
    pathname.startsWith("/chat/") ||
    pathname === "/builder" ||
    pathname.startsWith("/builder/") ||
    pathname === "/studio/images" ||
    pathname.startsWith("/studio/images/")
  );
}
