import type { BuilderTab } from "@/entities/content";

/**
 * builder-techspec.md §4-1(T-4) — 캐릭터 빌더 5탭의 단일 소스. `CharacterBuilderShell.tsx`가 그리던
 * 탭 목록을 여기로 옮기고 `fields`·`preview`(D-2, A-6)를 더했다.
 *
 * `detail` 탭 id는 스키마 키 `registration`과 이름이 다르다(builder-progress.md §0-2 조사) —
 * `fields`가 실제 경로를 가리키므로 매칭에는 영향이 없다.
 */
export const CHARACTER_TABS = [
  { id: "profile", label: "프로필", fields: ["profile"], preview: "card" },
  { id: "intro", label: "인트로", fields: ["intro"], preview: "chat" },
  { id: "prompt", label: "프롬프트", fields: ["prompt"], preview: "chat" },
  { id: "advanced", label: "고급기능", fields: ["situationalImages"], preview: "chat" },
  { id: "detail", label: "상세", fields: ["registration"], preview: "card" },
] as const satisfies readonly BuilderTab[];

/** `TabsTrigger`의 value 좁힘·활성 탭 atom이 쓰는 탭 id 유니언. `CHARACTER_TABS`에서 도출한다
 * (별도 유니언을 손으로 유지하지 않음). */
export type CharacterBuilderTab = (typeof CHARACTER_TABS)[number]["id"];
