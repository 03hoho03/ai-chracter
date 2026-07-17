import { atom } from "jotai";

export type Theme = "dark" | "light";

const THEME_STORAGE_KEY = "theme";

function readStoredTheme(): Theme {
  return localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
}

const storedThemeAtom = atom<Theme>(readStoredTheme());

/**
 * tasks/prd-monochrome-dark-mode.md FR-1~6 — 전역 테마 상태(기본 다크). 초기값은
 * index.html의 FOUC 방지 인라인 스크립트와 같은 규칙으로 localStorage `theme`을 읽고,
 * 변경 시 html의 dark 클래스 토글 + localStorage 저장까지 이 atom의 write가 책임진다.
 */
export const themeAtom = atom(
  (get) => get(storedThemeAtom),
  (_get, set, next: Theme) => {
    set(storedThemeAtom, next);
    localStorage.setItem(THEME_STORAGE_KEY, next);
    document.documentElement.classList.toggle("dark", next === "dark");
  },
);
