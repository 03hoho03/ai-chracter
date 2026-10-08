import type { QueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { novelKeys, type NovelJobResponse } from "@/entities/novel";

/** 화 작업이 202 로 시작된 뒤 언제나 일어나야 할 캐시 정리. 결과와 무관하게 항상 필요한 일이라 호출부가 아니라
 * 뮤테이션 정의에 둔다.
 *
 * - 202 응답으로 작업 캐시를 미리 채운다 — 폴링 첫 응답 전에도 "진행 중"을 그릴 수 있다.
 * - 상세는 낡았다: 서버가 `activeJob` 을 실었으니 다시 받아야 새로고침 없이도 다른 버튼이 잠긴다.
 * - 잔액·내역은 낡았다: 작업을 만들며 이미 차감했다. */
export function onNovelChapterJobStarted(queryClient: QueryClient, novelId: string, job: NovelJobResponse) {
  queryClient.setQueryData(novelKeys.job(novelId, job.id), job);
  void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
  void queryClient.invalidateQueries({ queryKey: cloverKeys.all });
}
