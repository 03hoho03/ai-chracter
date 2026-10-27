import { z } from "zod";

import { normalizeMyWorksQuery, type MyWorksParams } from "@/entities/work";

/** 유형 칩 한 줄. 값 이름은 서버 `GET /me/works` 의 `type` 과 같다. `all` 은 주소에 싣지 않는다 — 파라미터의 부재가
 * 곧 전체다. */
export const STUDIO_TYPE_FILTERS = ["all", "character", "story", "novel"] as const;

export type StudioTypeFilter = (typeof STUDIO_TYPE_FILTERS)[number];

/** 상태 셀렉트. 값 이름은 서버 `GET /me/works` 의 `status` 와 같고, 뜻도 서버 정의 하나를 따른다(공개 중은 공개 범위
 * 공개 ∧ 이용제한 아님, 수정본 있음은 공개 범위와 무관, 심사 중은 소설에만 있음). */
export const STUDIO_STATUS_FILTERS = ["all", "draft", "public", "changed", "review"] as const;

export type StudioStatusFilter = (typeof STUDIO_STATUS_FILTERS)[number];

/** 검색어 칸이 받는 주소 값. TanStack Router 는 주소의 값을 JSON 으로 먼저 읽어 손으로 친 `?q=1` 을 숫자 1로 넘긴다 —
 * 문자열만 받으면 그 검색이 소리 없이 사라지므로 숫자도 글자로 되돌려 받는다. 앱이 직접 쓰는 주소는 라우터가
 * 따옴표로 감싸 문자열로 돌아오므로 이 갈래를 타지 않는다. */
function toSearchQuery(value: string | number): string | undefined {
  return normalizeMyWorksQuery(typeof value === "number" ? String(value) : value);
}

/** 주소의 묶음 값이 묶음 id 모양이 아닐 때 남기는 표지. 부재로 떨어뜨리면 손으로 고친·잘린 묶음 주소가 소리 없이 홈
 * 목록이 되어 "이 묶음이 비었다"·"묶음 화면이 사라졌다"로 읽히므로, 묶음 화면 자리에서 찾을 수 없다고 말한다. */
export const UNREADABLE_BUNDLE = "unreadable";

/** 필터·검색은 전부 주소에 남아 새로고침·뒤로가기에서 보존된다. 기본값은 파라미터를 비워서 표현한다.
 * 모든 필드는 `.catch(undefined)` 로 끝난다 — 모르는 값을 거부하면 라우터가 `SearchParamError` 를 던져 앱 크롬 없는
 * 오류 상자만 남는다. 소설 칩·"심사 중" 을 볼 수 없는 계정이 그 값으로 들어오는 경우는 스키마가 아니라
 * `resolveStudioSearch` 가 접는다(허용 여부는 세션을 읽어야 안다). */
export const studioSearchSchema = z.object({
  type: z.enum(STUDIO_TYPE_FILTERS).exclude(["all"]).optional().catch(undefined),
  status: z.enum(STUDIO_STATUS_FILTERS).exclude(["all"]).optional().catch(undefined),
  q: z.union([z.string(), z.number()]).transform(toSearchQuery).optional().catch(undefined),
  // 묶음 id 는 서버가 uuid 로 받는다. `z.uuid()` 는 RFC 변형 비트까지 요구해 서버가 받는 id 도 거절할 수 있어, 서버
  // (파이썬 `uuid.UUID`)처럼 16진 8-4-4-4-12 모양만 보는 `z.guid()` 를 쓴다.
  bundle: z.guid().optional().catch(UNREADABLE_BUNDLE),
});

export type StudioSearch = z.infer<typeof studioSearchSchema>;

/** 스튜디오가 지금 보는 범위 — 모든 작품(홈)인지, 묶음 하나인지. */
export type StudioScope = { kind: "home" } | { kind: "bundle"; bundleId: string } | { kind: "unreadableBundle" };

export function resolveStudioScope(search: StudioSearch): StudioScope {
  if (search.bundle === undefined) return { kind: "home" };
  if (search.bundle === UNREADABLE_BUNDLE) return { kind: "unreadableBundle" };
  return { kind: "bundle", bundleId: search.bundle };
}

/**
 * 주소의 조건을 서버로 보낼 값으로 편다. **축의 기본값·소설 영역 판정·주소 `bundle` 을 서버 `bundleId` 로 옮기는 일은
 * 여기 하나에서만 한다** — 칩·셀렉트·쿼리
 * 키·빈 결과 문장이 모두 이 값을 본다.
 *
 * 소설 영역이 닫힌 계정이 `?type=novel`·`?status=review` 로 들어오면 그 축을 전체로 접는다. 그 칩과 항목이 화면에
 * 없으니 걸린 필터를 풀 방법이 없고, 서버도 그 계정에는 소설을 섞지 않아 늘 빈 목록이기 때문이다.
 */
export function resolveStudioSearch(search: StudioSearch, isNovelAreaVisible: boolean): MyWorksParams {
  const scope = resolveStudioScope(search);
  const type = search.type ?? "all";
  // 묶음 화면에는 상태 셀렉트가 없다 — 홈에서 걸어 둔 상태가 따라 들어오면 풀 방법이 없으니 전체로 접는다.
  const status = scope.kind === "home" ? (search.status ?? "all") : "all";

  return {
    type: !isNovelAreaVisible && type === "novel" ? "all" : type,
    status: !isNovelAreaVisible && status === "review" ? "all" : status,
    bundleId: scope.kind === "bundle" ? scope.bundleId : undefined,
    q: search.q,
  };
}

/** Radix 단일선택 토글은 선택된 항목을 다시 누르면 빈 문자열을 흘려보내고 `SelectItem` 의 value 도 `string` 이라,
 * 화면에서 돌아오는 값에는 좁힘이 필요하다. */
export function isStudioTypeFilter(value: string): value is StudioTypeFilter {
  return STUDIO_TYPE_FILTERS.some((filter) => filter === value);
}

export function isStudioStatusFilter(value: string): value is StudioStatusFilter {
  return STUDIO_STATUS_FILTERS.some((filter) => filter === value);
}
