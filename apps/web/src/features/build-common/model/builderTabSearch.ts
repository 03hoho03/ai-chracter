/** 탭 목록 — 첫 탭이 기본 탭이다(빌더는 언제나 프로필 탭에서 시작한다). */
type BuilderTabList<T extends string> = readonly [{ readonly id: T }, ...{ readonly id: T }[]];

/**
 * 주소의 `?tab=` 값으로 열 탭을 고른다. 없거나 이 빌더에 없는 탭 id 면 기본 탭이다 — 캐릭터·스토리 빌더가 한 라우트를
 * 쓰므로 주소는 어느 빌더의 탭 id 든 받을 수 있고, 다른 빌더의 탭 id(예: 캐릭터 빌더에 `?tab=mediaBook`)나 손으로 고친
 * 값도 여기서 기본 탭으로 접는다.
 */
export function tabFromSearch<T extends string>(raw: string | undefined, tabs: BuilderTabList<T>): T {
  return tabs.find((tab) => tab.id === raw)?.id ?? tabs[0].id;
}

/** 탭을 주소에 적을 값. 기본 탭은 파라미터를 지워(부재로) 나타낸다 — 기본값을 주소에 남기지 않는 저장소 관례다. */
export function tabToSearch<T extends string>(tab: T, tabs: BuilderTabList<T>): T | undefined {
  return tab === tabs[0].id ? undefined : tab;
}
