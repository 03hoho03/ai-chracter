/** 소설 캐시 키. 모두 `["novel", 종류, novelId, …]` 꼴이라 종류와 소설로 한꺼번에 가리킬 수 있다(`novelScoped`).
 *
 * 캐시 처방(어느 뮤테이션이 무엇을 고치나)은 각 뮤테이션 정의에 적고, 여기에는 키마다 "무엇이 이 값을 바꾸나"만 둔다
 * — 새 뮤테이션을 더할 때 이 목록을 보고 빠뜨린 캐시가 없는지 확인한다.
 *
 * - `detail`: 거의 모든 쓰기(화 생성·삭제·직접 수정·제목·작가의 말·노트·버전 되돌리기). 응답이 상세면 `setQueryData`.
 * - `chapter`·`revisions`: 그 화의 새 개정(직접 수정·AI 수정 적용·판 되돌리기·다시 만들기·버전 되돌리기).
 * - `revision`: 바뀌지 않는다(판은 만든 뒤 고치지 않는다).
 * - `characters`: 화 생성·다시 만들기(생성 출력의 인물이 붙는다), 인물 고치기·합치기, 버전 되돌리기(메모).
 * - `boardLayout`: 배치 저장뿐. 묶음 삭제·인물 합치기 뒤에는 서버가 없는 키를 빼고 주므로 고칠 필요가 없다.
 * - `snapshots`·`snapshot`: 버전 저장·지우기·되돌리기(자동 저장이 하나 생긴다), 마지막 묶음 삭제(그 화 항목이 지워진
 *   화가 된다).
 * - `chainEstimate`: 남은 대화가 바뀌는 모든 일(화 생성·삭제). 확인 화면을 열 때마다 새로 받는다. */
export const novelKeys = {
  all: ["novel"] as const,
  list: () => [...novelKeys.all, "list"] as const,
  detail: (novelId: string) => [...novelKeys.all, "detail", novelId] as const,
  job: (novelId: string, jobId: string) => [...novelKeys.all, "job", novelId, jobId] as const,
  /** 장 하나의 현재 본문. 소설 상세가 알려 준 현재 개정 id 를 키에 넣는다 — 상세가 새 개정을 알려 오면(다른 탭의
   * 수정·재생성) 키가 바뀌어 저절로 새로 받는다. */
  chapter: (novelId: string, chapterId: string, revisionId: string) =>
    [...novelKeys.all, "chapter", novelId, chapterId, revisionId] as const,
  /** 한 장의 모든 개정 캐시(현재 본문 캐시 전부)를 함께 가리킬 때. */
  chapterAll: (novelId: string, chapterId: string) => [...novelKeys.all, "chapter", novelId, chapterId] as const,
  revisions: (novelId: string, chapterId: string) => [...novelKeys.all, "revisions", novelId, chapterId] as const,
  revision: (novelId: string, chapterId: string, revisionId: string) =>
    [...novelKeys.all, "revision", novelId, chapterId, revisionId] as const,
  characters: (novelId: string) => [...novelKeys.all, "characters", novelId] as const,
  boardLayout: (novelId: string) => [...novelKeys.all, "boardLayout", novelId] as const,
  snapshots: (novelId: string) => [...novelKeys.all, "snapshots", novelId] as const,
  snapshot: (novelId: string, snapshotId: string) => [...novelKeys.all, "snapshot", novelId, snapshotId] as const,
  chainEstimate: (novelId: string) => [...novelKeys.all, "chainEstimate", novelId] as const,
};

/** 한 소설의 캐시 중 `kinds` 종류만 고르는 술어. `invalidateQueries({ queryKey: novelKeys.all, predicate })` 로
 * 쓴다 — 종류별 키가 소설 id 를 같은 셋째 자리에 두는 것을 이용한다. */
export function novelScoped(novelId: string, kinds: readonly string[]) {
  return (query: { queryKey: readonly unknown[] }) =>
    query.queryKey[2] === novelId && typeof query.queryKey[1] === "string" && kinds.includes(query.queryKey[1]);
}
