import { z } from "zod";

/** 서버와 같은 규칙을 먼저 건다 — 앞뒤 공백을 걷고 1~1,000자. 화면의 `trim` 은 유니코드 공백과 BOM 까지 걷고 서버도 같은
 * 범위로 걷는다. 1,000자는 이름·전→후와 함께 운영 디스코드 글 상한(2,000자) 안에 든다. */
export const reasonSchema = z.object({
  reason: z.string().trim().min(1, "사유를 입력해주세요.").max(1000, "사유는 1,000자까지 쓸 수 있어요."),
});

export type ReasonFormValues = z.infer<typeof reasonSchema>;
