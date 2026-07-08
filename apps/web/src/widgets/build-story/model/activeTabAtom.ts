import { atom } from "jotai";

/** techspec-builder-story.md §0 AC — 스토리 빌더 8탭. */
export type StoryBuilderTab =
  | "profile"
  | "setting"
  | "startingSetup"
  | "stat"
  | "keywordNote"
  | "shortcut"
  | "ending"
  | "registration";

export const storyBuilderActiveTabAtom = atom<StoryBuilderTab>("profile");
