/**
 * 조건부 클래스를 이어 붙인다. 거짓 값은 빠진다.
 *
 * 충돌하는 Tailwind 클래스를 정리하는 병합(tailwind-merge)은 하지 않는다 — 이 앱은 의존성을 늘리지 않으려고 그 패키지를
 * 들이지 않았다. 그래서 같은 속성을 두 번 덮어쓰는 조합(`px-2` 와 `px-3`)을 넘기지 않는다.
 */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
