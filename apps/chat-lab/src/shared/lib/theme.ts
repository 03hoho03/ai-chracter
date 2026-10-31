/** 손으로 고른 테마. `system` 은 고르지 않은 상태 — 운영체제 설정을 따른다. */
export type ThemePreference = "system" | "light" | "dark";

/** 저장 키. 첫 그림 전에 저장값을 붙이는 `index.html` 의 인라인 스크립트가 같은 키를 읽는다 — 바꾸면 그쪽도 바꾼다. */
const STORAGE_KEY = "chat-lab:theme";

/** 토글을 누를 때마다 도는 순서. 시스템으로 돌아오는 칸이 있어야 한 번 고른 뒤에도 운영체제 설정을 다시 따를 수 있다. */
const THEME_CYCLE = {
  system: "light",
  light: "dark",
  dark: "system",
} as const satisfies Record<ThemePreference, ThemePreference>;

export function nextThemePreference(current: ThemePreference): ThemePreference {
  return THEME_CYCLE[current];
}

/**
 * 지금 문서에 붙은 테마. 저장값은 `index.html` 이 첫 그림 전에 이미 붙였으므로 저장소를 다시 읽지 않고 문서를 본다 — 저장소를
 * 못 쓰는 창에서도 화면과 토글 글자가 어긋나지 않는다.
 */
export function readAppliedTheme(): ThemePreference {
  const applied = document.documentElement.dataset.theme;
  return applied === "light" || applied === "dark" ? applied : "system";
}

/**
 * 고른 테마를 문서에 붙이고 저장한다. `color-scheme` 도 함께 바꿔 스크롤바·기본 바탕처럼 브라우저가 그리는 부분이 따라오게 한다.
 * 저장이 실패해도 지금 화면에는 붙는다.
 */
export function applyThemePreference(preference: ThemePreference): void {
  const root = document.documentElement;
  if (preference === "system") {
    delete root.dataset.theme;
    root.style.colorScheme = "";
  } else {
    root.dataset.theme = preference;
    root.style.colorScheme = preference;
  }
  try {
    if (preference === "system") {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, preference);
    }
  } catch {
    // 저장소를 못 쓰는 창이다(사생활 보호 창, 사이트 데이터 차단) — 다음에 열 때 시스템 설정으로 돌아갈 뿐 지금 화면은 이미 바뀌었다.
  }
}
