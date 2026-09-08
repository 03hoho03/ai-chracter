import { z } from "zod";

import { INQUIRY_CATEGORIES } from "@/entities/inquiry";

/** techspec.md §5-4 — 서버 요청 타입(`InquiryCreateRequest`)으로의 변환은 모양이 같더라도
 * `./formToServer.ts`가 전담한다(`apps/web/CLAUDE.md` 폼 규약).
 *
 * ⚠️ `title`/`body`의 `max()`는 서버 `apps/api/src/api/inquiry/schemas.py`의
 * `Field(max_length=…)`와 같은 값이어야 한다 — 어긋나면 화면은 통과시키고 서버가 422로 거절한다. */
export const submitInquirySchema = z.object({
  category: z.enum(INQUIRY_CATEGORIES, { message: "문의 유형을 선택해주세요" }),
  title: z.string().min(1, { message: "제목을 입력해주세요" }).max(100),
  body: z.string().min(1, { message: "내용을 입력해주세요" }).max(2000),
  attachmentAssetId: z.string().optional(),
});

export type SubmitInquiryFormValues = z.infer<typeof submitInquirySchema>;

export const submitInquiryDefaultValues: SubmitInquiryFormValues = {
  // 카테고리에 자연스러운 기본값은 없다 — 목록의 첫 항목으로 둔다(`generate-images`의
  // model/aspectRatio 기본값과 같은 관용구).
  category: "account",
  title: "",
  body: "",
  attachmentAssetId: undefined,
};
