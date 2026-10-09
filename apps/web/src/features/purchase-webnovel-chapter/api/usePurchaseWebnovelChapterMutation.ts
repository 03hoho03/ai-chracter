import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { webnovelKeys } from "@/entities/webnovel";
import { apiClient } from "@/shared/api/client";

import { toPurchaseFailure } from "../model/purchaseFailure";

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
 * 잔액과 클로버 내역 세 탭도 낡았다(차감 행이 하나 생겼다).
 *
 * 두 거절도 화면의 그 화와 작품 정보가 낡았다는 뜻이다. 살 것이 없다(409 — 무료 화이거나 내가 공개한 소설)면 같은 둘을
 * 다시 받아 본문을 연다. 지금 소장할 수 없는 화(404 — 그사이 공개가 끝났다)면 둘을 비우고 다시 받는다 — 다시 받기만
 * 하면 실패해도 화면이 옛 데이터(잠긴 화)를 그대로 그려서, 비워야 다시 받은 실패(찾을 수 없음·열람 종료)가 보인다.
 * 실패에도 잔액은 다시 받는다 — 잔액 부족 거절은 화면의 잔액이 낡았다는 뜻이다. */
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
    onError: (error, { novelId, chapterId }) => {
      const { kind } = toPurchaseFailure(error);
      if (kind === "notForSale") {
        void queryClient.invalidateQueries({ queryKey: webnovelKeys.chapter(novelId, chapterId) });
        void queryClient.invalidateQueries({ queryKey: webnovelKeys.detail(novelId) });
      } else if (kind === "missing") {
        void queryClient.resetQueries({ queryKey: webnovelKeys.chapter(novelId, chapterId) });
        void queryClient.resetQueries({ queryKey: webnovelKeys.detail(novelId) });
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
    },
  });
}
