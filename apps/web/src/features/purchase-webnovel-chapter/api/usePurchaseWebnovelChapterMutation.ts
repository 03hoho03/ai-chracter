import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { webnovelKeys } from "@/entities/webnovel";
import { apiClient } from "@/shared/api/client";

type PurchaseResponse = components["schemas"]["NovelChapterPurchaseResponse"];

type PurchaseVariables = {
  novelId: string;
  chapterId: string;
  /** 확인 화면에 보인 가격. 서버의 지금 가격과 다르면 사지 않는다(409 와 지금 가격). */
  expectedPrice: number;
};

/** `POST /webnovels/{novelId}/chapters/{chapterId}/purchase` — 노벨 화 하나를 소장한다. 이미 소장한 화면 차감 없이
 * 같은 응답이다(`charged: 0`).
 *
 * 성공하면 그 화(잠김 → 본문)와 작품 정보(목차의 가격 표식)를 다시 받는다 — 같은 주소의 화면이 그대로 본문을 연다.
 * 잔액과 클로버 내역 세 탭도 낡았다(차감 행이 하나 생겼다). 실패에도 잔액은 다시 받는다 — 잔액 부족 거절은 화면의
 * 잔액이 낡았다는 뜻이다. */
export function usePurchaseWebnovelChapterMutation() {
  const queryClient = useQueryClient();
  return useMutation<PurchaseResponse, ApiError, PurchaseVariables>({
    mutationFn: async ({ novelId, chapterId, expectedPrice }) =>
      (
        await apiClient.post<PurchaseResponse>(`/webnovels/${novelId}/chapters/${chapterId}/purchase`, {
          expectedPrice,
        })
      ).data,
    onSuccess: (_data, { novelId, chapterId }) => {
      void queryClient.invalidateQueries({ queryKey: webnovelKeys.chapter(novelId, chapterId) });
      void queryClient.invalidateQueries({ queryKey: webnovelKeys.detail(novelId) });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.ledgers() });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
    },
  });
}
