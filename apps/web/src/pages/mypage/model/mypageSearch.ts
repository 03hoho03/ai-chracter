import { z } from "zod";

/** `/mypage` 의 서치 파라미터 — 본인인증창이 페이지를 떠났다가(모바일) 돌아올 때 포트원이 붙이는 것 중 화면이 읽는 둘.
 * 숫자로만 된 값은 라우터가 숫자로 주므로 문자열로 되돌린다(`code` 를 버리면 실패한 인증을 저장하러 간다). */
export const mypageSearchSchema = z.object({
  identityVerificationId: z.coerce.string().optional().catch(undefined),
  code: z.coerce.string().optional().catch(undefined),
});

export type MypageSearch = z.infer<typeof mypageSearchSchema>;
