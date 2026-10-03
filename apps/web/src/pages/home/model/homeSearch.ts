import { z } from "zod";

import { CONTENT_LIST_SORTS, CONTENT_TYPES } from "@/entities/content";

// 유형·정렬·장르·크리에이터·해시태그·검색어를 모두 홈 라우트의 URL search param으로 관리해 새로고침·공유
// 시에도 유지되게 한다(헤더 검색 인라인 익스팬드도 q를 이 스키마로 갱신).
// 모든 필드는 `.catch(undefined)`로 끝난다 — 모르는 값(오래된 링크·손으로 고친 URL)이 와도 그 축만
// 기본값(= 파라미터의 부재)으로 떨어지고 페이지는 렌더된다(`apps/web/CLAUDE.md`의 `validateSearch` 규칙).
// 라우트 파일이 아니라 여기 두는 이유는 vitest로 파싱을 시험하기 위해서다(라우트 모듈은 `node` 환경에서
// import하면 죽는다).
export const homeSearchSchema = z.object({
  // 기본 유형(스토리)은 `.exclude()`로 뺀다 — `?type=story`를 쓰는 `<Link>`·`navigate`가 타입 단계에서
  // 막혀 "부재가 곧 스토리"가 지켜진다. 기본값을 고른 근거는 `entities/content`의 `resolveHomeContentType`.
  type: z.enum(CONTENT_TYPES).exclude(["story"]).optional().catch(undefined),
  q: z.string().optional().catch(undefined),
  sort: z.enum(CONTENT_LIST_SORTS).optional().catch(undefined),
  genre: z.string().optional().catch(undefined),
  creator: z.string().optional().catch(undefined),
  hashtag: z.string().optional().catch(undefined),
});

export type HomeSearch = z.infer<typeof homeSearchSchema>;

/** 목록을 거르는 축. 유형은 목록 자체를 바꾸고 정렬은 순서만 바꾸므로 여기 없다 — `필터 지우기`가 이
 * 넷만 비우고, 빈 상태·끝 문구가 "조건이 걸렸는지"를 이 넷으로 판단한다. */
const HOME_FILTER_KEYS = ["genre", "q", "creator", "hashtag"] as const satisfies readonly (keyof HomeSearch)[];

export function hasHomeFilter(search: HomeSearch): boolean {
  return HOME_FILTER_KEYS.some((key) => Boolean(search[key]));
}

/** `필터 지우기`가 search에 덮는 패치. 키 목록이 위 `HOME_FILTER_KEYS`와 어긋나면 `Record`가 컴파일을 깬다. */
export const HOME_FILTER_RESET: Record<(typeof HOME_FILTER_KEYS)[number], undefined> = {
  genre: undefined,
  q: undefined,
  creator: undefined,
  hashtag: undefined,
};
