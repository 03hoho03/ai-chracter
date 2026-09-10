/**
 * builder-techspec.md §4-1 — 빌더 탭 하나의 선언. 라벨·에러 매칭용 필드 프리픽스·프리뷰 종류가 이 한
 * 타입에 모인다(단일 소스). `features/build-story`·`features/build-character`(탭 목록 선언)와
 * `widgets/build-common`(에러 매칭)이 함께 쓰는데, features가 widgets를 import할 수 없어(FSD 레이어
 * 역전) 둘 다에서 참조 가능한 최하위 레이어인 shared에 둔다.
 *
 * 폼 값 타입으로 제네릭을 두지 않는다 — `fields`는 `*`(배열 인덱스 와일드카드)를 쓰는 경로 프리픽스
 * 문자열이라 특정 폼 타입의 키 구조로 표현할 수 없고(구조적으로 아무것도 좁히지 못한다), 저장소
 * eslint는 쓰이지 않는 타입 매개변수를 에러로 잡는다(`@typescript-eslint/no-unused-vars`). 폼 값
 * 타입과의 연결이 필요한 자리(`errorTabs`/`firstErrorLocation`의 `errors: FieldErrors<T>`)는 그
 * 함수 시그니처의 제네릭이 담당한다.
 */
export type BuilderTab = {
  id: string;
  label: string;
  /** 경로 프리픽스 배열. **최상위 키가 아니다** — `*`는 배열 인덱스 한 칸에 대응한다
   * (`startingSetups.*.stats`처럼). */
  fields: readonly string[];
  /** 이 탭에서 보여줄 프리뷰 종류(D-2, A-6 — 카드·대화 2종). */
  preview: "card" | "chat";
};
