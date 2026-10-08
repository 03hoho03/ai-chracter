import { atom } from "jotai";

export const THEMES = ["dark", "light"] as const;
export type Theme = (typeof THEMES)[number];

export function isTheme(value: string): value is Theme {
  return THEMES.some((theme) => theme === value);
}

const THEME_STORAGE_KEY = "theme";

type ThemeStorage = Pick<Storage, "getItem" | "setItem">;

/** 사이트 데이터가 차단된 브라우저에서는 `localStorage` 참조 자체가 던진다. 이 atom 은 앱이 뜰 때 모듈 최상위에서
 * 읽히므로, 여기서 던지면 앱 전체가 빈 화면이 된다. */
function browserStorage(): ThemeStorage {
  return window.localStorage;
}

/** 저장된 테마. "light" 일 때만 라이트, 그 밖(값 없음·저장소 막힘 포함)은 다크다 — index.html 의 인라인 스크립트와
 * 같은 규칙이다. */
export function readStoredTheme(getStorage: () => ThemeStorage = browserStorage): Theme {
  try {
    return getStorage().getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

/** 고른 테마를 저장한다. 저장소가 막혔으면 이번 방문에만 적용되고 다음 방문은 기본값(다크)으로 돌아간다. */
export function writeStoredTheme(theme: Theme, getStorage: () => ThemeStorage = browserStorage): void {
  try {
    getStorage().setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // 저장하지 못해도 화면 테마는 바뀐다.
  }
}

const storedThemeAtom = atom<Theme>(readStoredTheme());

/**
 * 전역 테마 상태(기본 다크). 초기값은
 * index.html의 FOUC 방지 인라인 스크립트와 같은 규칙으로 localStorage `theme`을 읽고,
 * 변경 시 html의 dark 클래스 토글 + localStorage 저장까지 이 atom의 write가 책임진다.
 */
export const themeAtom = atom(
  (get) => get(storedThemeAtom),
  (_get, set, next: Theme) => {
    set(storedThemeAtom, next);
    writeStoredTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
  },
);
