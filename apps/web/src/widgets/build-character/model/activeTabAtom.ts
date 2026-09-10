import { atom } from "jotai";

// 탭 id 유니언(`CharacterBuilderTab`)은 features/build-character/model/tabs.ts의 CHARACTER_TABS에서
// 도출되고 그쪽이 소유한다(builder-techspec.md §4-1) — features가 widgets를 import할 수 없어(FSD 레이어
// 역전, eslint import-x/no-restricted-paths) 여기서 다시 선언하지 않고 `@/features/build-character`에서
// 가져다 쓴다.
import type { CharacterBuilderTab } from "@/features/build-character";

export const characterBuilderActiveTabAtom = atom<CharacterBuilderTab>("profile");
