import { z } from "zod";

/** 편집 보드 주소의 서치. 고른 것은 `?select=` 하나다(값의 꼴은 `widgets/novel-board` 의 `parseBoardSelection` 이
 * 판정한다). 차단 함수가 다음 주소의 서치를 이 스키마로 다시 읽는다 — 라우트의 같은 스키마를 가져오면 그 라우트
 * 모듈이 이 페이지를 다시 가져와 순환한다. 어긋난 값은 부재(고른 것 없음)로 접는다. */
export const novelBoardSearchSchema = z.object({
  select: z.string().optional().catch(undefined),
});
