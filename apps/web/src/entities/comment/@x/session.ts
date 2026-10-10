// entities/session 전용 공개 API. 로그아웃·탈퇴·로그인 때 앞 계정의 캐시를 비우려고 키를 넘기고, 로그아웃·탈퇴 때
// 댓글 초안을 버리게 하는 리비전도 넘긴다.
export { commentKeys } from "../api/keys";
export { commentDraftLogoutRevisionAtom } from "../model/atoms";
