import type { QueryClient } from "@tanstack/react-query";

import { sessionKeys, type AdminMeResponse } from "@/entities/session";

import type { AdminFeatureSwitchChangeResult, AdminFeatureSwitchListResponse } from "../model/types";
import { featureSwitchKeys } from "./keys";

/**
 * 저장이 성공하면 응답의 행으로 목록 캐시를 바로 갈아 끼우고(행이 다시 받을 때까지 옛 값으로 남지 않게) 목록·이력을 다시
 * 받는다. 응답의 `switch` 가 없으면 이 화면이 모르는 이름의 덮어쓰기를 지운 것이라 그 행을 뺀다.
 *
 * 노벨 공개 정책은 `/admin/me` 도 들고 있어(어드민 노벨·작품 조치의 환급 문구가 이 값을 따른다) 그 캐시를 응답의 실효 값으로
 * 직접 고친다. 다시 받지 않는 이유: `/admin/me` 는 그 요청을 받은 서버 프로세스의 스위치 맵으로 값을 싣는데, 다른 프로세스의
 * 맵은 저장을 길어야 한 갱신 간격 늦게 따라온다. 그 사이에 다시 받으면 옛 값이 오고, 세션 쿼리는 다시 받지 않는 캐시라 옛
 * 값이 새로고침 전까지 남는다. 저장 응답은 표에 쓴 결과로 계산한 값이라 이 어긋남이 없다.
 */
export function applySavedSwitch(queryClient: QueryClient, name: string, result: AdminFeatureSwitchChangeResult) {
  const saved = result.switch;
  queryClient.setQueryData<AdminFeatureSwitchListResponse>(featureSwitchKeys.list(), (prev) => {
    if (prev === undefined) return prev;
    if (saved === null) {
      return { ...prev, unknownOverrides: prev.unknownOverrides.filter((override) => override.name !== name) };
    }
    return { ...prev, adjustable: prev.adjustable.map((item) => (item.name === saved.name ? saved : item)) };
  });
  if (saved?.name === "novel_public_policy_v2_enabled") {
    queryClient.setQueryData<AdminMeResponse>(sessionKeys.current(), (prev) =>
      prev === undefined ? prev : { ...prev, novelPublicPolicyV2Enabled: saved.effectiveValue },
    );
  }
  void queryClient.invalidateQueries({ queryKey: featureSwitchKeys.all });
}
