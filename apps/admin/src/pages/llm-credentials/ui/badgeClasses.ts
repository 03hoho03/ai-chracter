/** 배지는 전용 프리미티브 없이 자리마다 손으로 조립한다. 상태는 윤곽(중립)이나 `destructive` 틴트(문제, 테두리 없음), 타입은 채움이라
 * 형태로도 갈린다. `secondary` 채움 위에는 흐린 글자를 올리지 않는다(라이트 대비 미달). */
export const NEUTRAL_BADGE_CLASS =
  "inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground";
export const PROBLEM_BADGE_CLASS =
  "inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-badge font-medium text-destructive-text";
export const TYPE_BADGE_CLASS =
  "inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-badge font-medium text-secondary-foreground";
