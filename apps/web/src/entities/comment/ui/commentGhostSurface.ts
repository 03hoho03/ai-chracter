/** 댓글 안 `ghost` 버튼의 hover 채움. 기본 hover(`bg-muted`)는 두 자리에서 표면과 같은 값이라 사라진다 —
 * 모달(`popover` 표면) 안에서는 `secondary`로 한 칸 올리고, 알림 대상으로 강조된 행(`CommentRow`가
 * `data-comment-highlighted`와 함께 `bg-secondary`를 깐다) 안에서는 그 `secondary`마저 같아지므로
 * 글자색 반투명(`foreground/10`)을 쓴다. 이 행 속성을 아는 쪽이 이 슬라이스라 여기서 함께 정한다. */
export const COMMENT_GHOST_HOVER_CLASS_NAME =
  "in-data-[slot=dialog-content]:not-in-data-[comment-highlighted=true]:hover:bg-secondary in-data-[comment-highlighted=true]:hover:bg-foreground/10";

/** 메뉴 트리거처럼 열린 동안 채움이 남는 버튼용 — 위와 같은 이유로 열린 상태(`data-state=open`)에도 같은 값을 준다. */
export const COMMENT_GHOST_OPEN_CLASS_NAME =
  "in-data-[slot=dialog-content]:not-in-data-[comment-highlighted=true]:data-[state=open]:bg-secondary in-data-[comment-highlighted=true]:data-[state=open]:bg-foreground/10";
