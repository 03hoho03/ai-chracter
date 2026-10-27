import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { WorkListResponse } from "../model/workItem";
import { workKeys } from "./keys";

/** 묶음에 든 작품을 `kind:id` 집합으로 — `GET /me/works?bundleId=` 를 커서 끝까지 따라간다. 서버에 "이 작품이 이 묶음에
 * 들었나"를 묶음 쪽에서 묻는 조회가 없어, 받은 첫 페이지만으로 표시하면 뒤 페이지의 작품이 "안 넣음"으로 보인다. 한 묶음은
 * 상한(500개)이 있어 요청 수도 그만큼으로 묶인다. */
export function useWorkBundleMembersQuery(bundleId: string) {
  return useQuery<ReadonlySet<string>, ApiError>({
    queryKey: workKeys.bundleMembers(bundleId),
    queryFn: async () => {
      const members = new Set<string>();
      let cursor: string | undefined;
      do {
        const page = (
          await apiClient.get<WorkListResponse>("/me/works", {
            params: { type: "all", status: "all", bundleId, cursor },
          })
        ).data;
        for (const item of page.items) members.add(toWorkMemberKey(item.kind, item.id));
        cursor = page.nextCursor ?? undefined;
      } while (cursor !== undefined);
      return members;
    },
  });
}

/** 묶음 소속을 가리는 작품 키. 캐릭터·스토리와 소설은 id 공간이 달라 종류를 함께 쓴다. */
export function toWorkMemberKey(kind: string, id: string): string {
  return `${kind}:${id}`;
}
