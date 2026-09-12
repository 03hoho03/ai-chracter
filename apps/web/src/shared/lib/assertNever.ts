/** fe-typescript TS-05 — 유니언 분기의 exhaustiveness 를 컴파일 시점에 강제한다. switch 의 default
 * (또는 최종 else)에서 호출하면, 유니언에 멤버가 늘었을 때 `x: never` 가 깨져 컴파일 에러가 나고
 * 런타임에 닿으면 throw 한다. */
export function assertNever(x: never): never {
  throw new Error(`Unexpected value: ${JSON.stringify(x)}`);
}
