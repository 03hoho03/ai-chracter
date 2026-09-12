/**
 * builder-techspec.md §4-1 — 빌더 탭 하나의 선언. 라벨·에러 매칭용 필드 프리픽스·프리뷰 종류가 이 한
 * 타입에 모인다(단일 소스). 셋 다 콘텐츠 초안을 어떻게 나눠 보여주느냐에 대한 서술이라, 초안 본문
 * (`useContentDraftQuery`·`createEmptyDraft`)을 이미 품는 `entities/content`가 집이다
 * (`fe-convention-refactor-goal-prompt.md R-4`). 소비처는 `features/build-story`·
 * `features/build-character`(탭 목록 선언)와 `features/build-common`(에러 매칭·탭 스트립)으로 전부
 * features다.
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
