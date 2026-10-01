import { z } from "zod";

/**
 * SSE 이벤트가 싣는 그림 맵의 스키마. REST 변환(`toMediaTagImages`)과 같은 모양으로 파싱한다(null 크기 → 비움). 맵을 생략하는 서버와도
 * 맞물리게 선택 필드다.
 */
export const mediaTagImagesSchema = z
  .record(
    z.string(),
    z.object({
      url: z.string(),
      width: z
        .number()
        .nullish()
        .transform((value) => value ?? undefined),
      height: z
        .number()
        .nullish()
        .transform((value) => value ?? undefined),
    }),
  )
  .optional();
