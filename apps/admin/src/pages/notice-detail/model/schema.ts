import { z } from "zod";

/** ⚠️ 서버(`apps/api/src/api/admin/notices.py`)는 제목·본문에 길이 제약을 **걸지 않는다** —
 * 빈 제목도 201로 저장되고 그대로 게시까지 된다. 이 `min(1)`이 그걸 막는 유일한 관문이다
 * (`submit-inquiry/model/schema.ts`와 달리 맞춰야 할 서버 `max_length`가 없다). */
export const noticeEditorSchema = z.object({
  title: z.string().min(1, { message: "제목을 입력해주세요" }),
  bodyMarkdown: z.string().min(1, { message: "본문을 입력해주세요" }),
});

export type NoticeEditorFormValues = z.infer<typeof noticeEditorSchema>;
