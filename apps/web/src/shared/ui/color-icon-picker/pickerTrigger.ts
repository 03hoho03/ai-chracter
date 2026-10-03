/** 색·아이콘 피커 트리거의 모양. 바로 옆 이름 칸(`Input`)과 같은 36px 티어라 반경도 같은 `rounded-lg` 이고(DESIGN.md
 * Components 절의 반경 정책), 포커스는 `Input`·`Button` 과 같은 하우스 레시피(`border-ring` + `ring-3 ring-ring/50`)다 —
 * UA 기본 아웃라인은 다크에서 이웃 컨트롤의 3px 링보다 확연히 약했다. 오류 상태도 `Input` 과 같은 붉은 테두리·옅은 링이다.
 * 터치 화면에서는 같은 머리 줄의 토글·삭제 버튼처럼 40px 로 커진다. */
export const PICKER_TRIGGER_CLASSNAME =
  "flex size-9 shrink-0 items-center justify-center rounded-lg border border-input outline-none motion-safe:transition-colors hover:bg-secondary/50 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 pointer-coarse:size-10";

/**
 * 트리거의 접근 이름. 고른 값이 있으면 그 값을 말하고("아이콘: 피로, 바꾸기"), 없으면 고르라고 말한다("아이콘 고르기
 * (필수)"). 그림만 있는 버튼이라 이름이 값을 말하지 않으면 스크린리더 사용자는 패널을 열어야 지금 값을 안다.
 */
export function triggerAccessibleName(label: string, selectedLabel: string | undefined, isRequired: boolean): string {
  if (selectedLabel !== undefined) return `${label}: ${selectedLabel}, 바꾸기`;
  return isRequired ? `${label} 고르기 (필수)` : `${label} 고르기`;
}
