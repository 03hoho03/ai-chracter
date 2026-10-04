type MessageAtPosition = {
  index: number;
  role: "user" | "assistant";
  contentType: "character" | "story";
};

/**
 * 글 속 미디어 북 태그를 그림으로 그리는 메시지인가 — 스토리 방의 첫 assistant 메시지(작성자의 시작상황·프롤로그
 * 복사본)뿐이다. 서버도 이 메시지에 대해서만 그림 맵을 준다. 그 밖(사용자 메시지·모델 응답·캐릭터 인사말)은 태그가
 * 글자 그대로 남는다 — 사용자가 칸 id 를 쳐서 그림을 불러내지 못하게, 캐릭터 화면은 이전과 같게.
 */
export function isAuthorOpeningMessage({ index, role, contentType }: MessageAtPosition): boolean {
  return contentType === "story" && index === 0 && role === "assistant";
}

/**
 * 글 속 `{{user}}`·`{{char}}` 를 이름으로 바꿔 그리는 메시지인가 — 스토리·캐릭터 방의 첫 assistant 메시지(작성자의
 * 시작상황·프롤로그·인트로 복사본)다. 미디어 북 그림과 달리 캐릭터 인사말도 작성자 글이라 포함한다. 사용자 메시지는
 * 보낼 때 이미 바꿔 저장했고, 모델 응답은 작성자 글이 아니라 손대지 않는다.
 */
export function isAuthorTextMessage({ index, role }: Omit<MessageAtPosition, "contentType">): boolean {
  return index === 0 && role === "assistant";
}
