import { z } from "zod";

import { countCommentGraphemes } from "@/entities/comment";

const selectedAuthorSchema = z.object({
  id: z.string().uuid(), nickname: z.string(), profileImageUrl: z.string().nullable(), isCreator: z.boolean(),
});

// 상한과 그 안내 문구는 스키마·입력 UI(카운터·멘션 선택 차단)·서버 오류 매핑이 함께 읽는다 — 값을 바꿀 때
// 한 곳만 고치면 카운터 색과 선택 차단이 검증과 따로 논다.
export const COMMENT_MAX_GRAPHEMES = 1000;
export const COMMENT_MAX_MENTIONS = 3;
export const COMMENT_TOO_LONG_MESSAGE = `댓글은 ${COMMENT_MAX_GRAPHEMES.toLocaleString("ko-KR")}자까지 입력할 수 있어요.`;
export const COMMENT_MENTION_LIMIT_MESSAGE = `멘션은 최대 ${COMMENT_MAX_MENTIONS}명까지 선택할 수 있어요.`;

export const commentFormSchema = z.object({
  body: z.string().refine((body) => countCommentGraphemes(body) <= COMMENT_MAX_GRAPHEMES, COMMENT_TOO_LONG_MESSAGE),
  stickerId: z.string().nullable(),
  isSpoiler: z.boolean(),
  mentions: z.array(selectedAuthorSchema).max(COMMENT_MAX_MENTIONS, COMMENT_MENTION_LIMIT_MESSAGE)
    .refine((mentions) => new Set(mentions.map((author) => author.id)).size === mentions.length, "이미 선택한 사용자예요."),
}).refine((values) => !!values.body.trim() || !!values.stickerId, {
  message: "댓글 내용이나 스티커를 입력해주세요.", path: ["body"],
});

export type CommentFormValues = z.infer<typeof commentFormSchema>;

export const EMPTY_COMMENT_VALUES: CommentFormValues = { body: "", stickerId: null, isSpoiler: false, mentions: [] };
