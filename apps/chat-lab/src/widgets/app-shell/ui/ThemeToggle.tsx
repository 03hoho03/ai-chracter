import { useState } from "react";

import {
  applyThemePreference,
  nextThemePreference,
  readAppliedTheme,
  type ThemePreference,
} from "@/shared/lib/theme";
import { Button } from "@/shared/ui/Button";

const THEME_LABELS = {
  system: "시스템",
  light: "라이트",
  dark: "다크",
} as const satisfies Record<ThemePreference, string>;

/** 시스템 → 라이트 → 다크 → 시스템 순으로 도는 테마 토글. 버튼 글자가 지금 고른 값이다. */
export function ThemeToggle() {
  const [preference, setPreference] = useState(readAppliedTheme);
  const next = nextThemePreference(preference);

  function handleClick() {
    applyThemePreference(next);
    setPreference(next);
  }

  return (
    <Button
      onClick={handleClick}
      aria-label={`테마 ${THEME_LABELS[preference]} — 누르면 ${THEME_LABELS[next]}`}
      title={`누르면 ${THEME_LABELS[next]}`}
    >
      <span aria-hidden="true">◐</span>
      <span className="hidden sm:inline">{THEME_LABELS[preference]}</span>
    </Button>
  );
}
