import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { workBundleKeys, workKeys, type WorkBundleKind } from "@/entities/work";
import { apiClient } from "@/shared/api/client";

import { addWorksInOrder, type AddWorksResult } from "../model/addWorks";

// 쓰기는 전부 `useMutation` 을 거친다 — 만들기·이름 바꾸기·넣기는 재동의 전 계정에 403 이고, 그 403 을 전역 처리
// (세션을 다시 읽어 재동의 모달)가 뮤테이션 캐시에서만 잡는다.

export type WorkBundleItemRef = { kind: WorkBundleKind; id: string };

/** 넣기·빼기 뒤에 낡는 것: 묶음 목록(항목 수·순서·`containsWork`)과 작품 목록(묶음 화면 목록·소속 집합). */
function invalidateAfterItemChange(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: workBundleKeys.all });
  void queryClient.invalidateQueries({ queryKey: workKeys.lists() });
}

function itemPath(bundleId: string, work: WorkBundleItemRef) {
  return `/me/work-bundles/${bundleId}/items/${work.kind}/${work.id}`;
}

/** `POST /me/work-bundles` — 새 묶음의 id 를 돌려준다. */
export function useCreateWorkBundleMutation() {
  const queryClient = useQueryClient();
  return useMutation<string, ApiError, string>({
    mutationFn: async (name) => (await apiClient.post<{ id: string }>("/me/work-bundles", { name })).data.id,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: workBundleKeys.all }),
  });
}

/** `PATCH /me/work-bundles/{id}` — 같은 이름이면 서버가 아무것도 바꾸지 않는다. */
export function useRenameWorkBundleMutation() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, { bundleId: string; name: string }>({
    mutationFn: async ({ bundleId, name }) => {
      await apiClient.patch(`/me/work-bundles/${bundleId}`, { name });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: workBundleKeys.all }),
  });
}

/** `DELETE /me/work-bundles/{id}` — 묶음과 소속만 지운다(작품은 그대로).
 *
 * 성공 뒤 캐시 정리는 호출부가 **화면을 옮긴 뒤에** 한다(`clearDeletedWorkBundle`). 보고 있던 묶음 화면이 먼저 다시 받으면
 * 목록에서 자기 id 를 못 찾아 "찾을 수 없어요"를 한 번 그리거나, 지운 묶음의 작품 목록을 다시 받아 404 가 난다. */
export function useDeleteWorkBundleMutation() {
  return useMutation<void, ApiError, string>({
    mutationFn: async (bundleId) => {
      await apiClient.delete(`/me/work-bundles/${bundleId}`);
    },
  });
}

/** 지운 묶음의 캐시를 정리한다 — 묶음 목록은 다시 받고, 그 묶음의 작품 목록은 버린다(다시 받으면 404 다). */
export function clearDeletedWorkBundle(queryClient: QueryClient, bundleId: string) {
  void queryClient.invalidateQueries({ queryKey: workBundleKeys.all });
  queryClient.removeQueries({ queryKey: workKeys.lists(), predicate: (query) => query.queryKey.includes(bundleId) });
}

/** `PUT …/items/{kind}/{workId}` — 작품 하나를 넣는다(이미 들었으면 그대로). */
export function usePutWorkBundleItemMutation() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, { bundleId: string; work: WorkBundleItemRef }>({
    mutationFn: async ({ bundleId, work }) => {
      await apiClient.put(itemPath(bundleId, work));
    },
    onSettled: () => invalidateAfterItemChange(queryClient),
  });
}

/** `DELETE …/items/{kind}/{workId}` — 작품 하나를 뺀다(들어 있지 않아도 성공). 재동의 전에도 열려 있다. */
export function useRemoveWorkBundleItemMutation() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, { bundleId: string; work: WorkBundleItemRef }>({
    mutationFn: async ({ bundleId, work }) => {
      await apiClient.delete(itemPath(bundleId, work));
    },
    onSettled: () => invalidateAfterItemChange(queryClient),
  });
}

/** 고른 작품 여럿을 순서대로 넣는다. 다시 받기는 다 보낸 뒤 한 번이다.
 *
 * 재동의로 멈췄으면 그 오류를 다시 던진다 — 뮤테이션 실패로 끝나야 전역 처리가 재동의 모달을 띄운다. */
export function useAddWorksToBundleMutation() {
  const queryClient = useQueryClient();
  return useMutation<AddWorksResult, ApiError, { bundleId: string; works: readonly WorkBundleItemRef[] }>({
    mutationFn: async ({ bundleId, works }) => {
      const result = await addWorksInOrder(works, async (work) => {
        await apiClient.put(itemPath(bundleId, work));
      });
      if (result.stoppedBy === "reconsent") throw result.stopError;
      return result;
    },
    onSettled: () => invalidateAfterItemChange(queryClient),
  });
}
