import { z } from "zod";

import { countCommentGraphemes } from "@/entities/comment";

const selectedAuthorSchema = z.object({
  id: z.string().uuid(), nickname: z.string(), profileImageUrl: z.string().nullable(), isCreator: z.boolean(),
});

export const commentFormSchema = z.object({
  body: z.string().refine((body) => countCommentGraphemes(body) <= 1000, "댓글은 1,000자까지 입력할 수 있어요."),
  stickerId: z.string().nullable(),
  isSpoiler: z.boolean(),
  mentions: z.array(selectedAuthorSchema).max(3, "멘션은 최대 3명까지 선택할 수 있어요.")
    .refine((mentions) => new Set(mentions.map((author) => author.id)).size === mentions.length, "이미 선택한 사용자예요."),
}).refine((values) => !!values.body.trim() || !!values.stickerId, {
  message: "댓글 내용이나 스티커를 입력해주세요.", path: ["body"],
});

export type CommentFormValues = z.infer<typeof commentFormSchema>;

export const EMPTY_COMMENT_VALUES: CommentFormValues = { body: "", stickerId: null, isSpoiler: false, mentions: [] };
