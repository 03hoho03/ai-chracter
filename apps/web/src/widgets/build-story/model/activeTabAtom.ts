import { atom } from "jotai";

// 탭 id 유니언(`StoryBuilderTab`)은 features/build-story/model/tabs.ts의 STORY_TABS에서 도출되고
// 그쪽이 소유한다(builder-techspec.md §4-1) — features가 widgets를 import할 수 없어(FSD 레이어 역전,
// eslint import-x/no-restricted-paths) 여기서 다시 선언하지 않고 `@/features/build-story`에서 가져다 쓴다.
import type { StoryBuilderTab } from "@/features/build-story";

export const storyBuilderActiveTabAtom = atom<StoryBuilderTab>("profile");
