import type { BuilderTab } from "@/shared/model/builderTab";

/**
 * builder-techspec.md §4-1(T-4) — 스토리 빌더 8탭의 단일 소스. `StoryBuilderShell.tsx`가 그리던
 * 탭 목록을 여기로 옮기고 `fields`(에러 탭 매칭용 경로 프리픽스)·`preview`(D-2, A-6)를 더했다.
 *
 * `fields`는 **최상위 키가 아니다** — `startingSetups`가 `startingSetup`/`stat`/`ending` 세 탭에
 * 걸쳐 있다(builder-progress.md §0-2 조사, techspec 원래 전제를 반증). `stat`/`ending`이 더 구체적인
 * 프리픽스이지만 배열 순서는 표시 순서(`startingSetup`이 먼저)를 따른다 — 매칭 우선순위는
 * `errorTabs`가 프리픽스 길이로 판정하므로 이 배열의 순서에 의존하지 않는다(A-1).
 */
export const STORY_TABS = [
  { id: "profile", label: "프로필", fields: ["profile"], preview: "card" },
  { id: "setting", label: "설정", fields: ["storySetting"], preview: "chat" },
  { id: "startingSetup", label: "시작설정", fields: ["startingSetups"], preview: "chat" },
  { id: "stat", label: "스탯", fields: ["startingSetups.*.stats"], preview: "chat" },
  { id: "keywordNote", label: "키워드북", fields: ["keywordNotes"], preview: "chat" },
  { id: "shortcut", label: "단축어", fields: ["shortcuts"], preview: "chat" },
  { id: "ending", label: "엔딩", fields: ["startingSetups.*.endings"], preview: "chat" },
  { id: "registration", label: "등록", fields: ["registration"], preview: "card" },
] as const satisfies readonly BuilderTab[];

/** `TabsTrigger`의 value 좁힘·활성 탭 atom이 쓰는 탭 id 유니언. `STORY_TABS`에서 도출해 탭 추가 시
 * 이 타입이 자동으로 따라오게 한다(별도 유니언을 손으로 유지하지 않음). */
export type StoryBuilderTab = (typeof STORY_TABS)[number]["id"];
