import type { QueryClient } from "@tanstack/react-query";

import { chatModelKeys, type ChatModel, type ChatModelId } from "@/entities/chat-model";
import { isCloverPriceChangedError } from "@/entities/clover";

import { previewTurnCost } from "./previewChatModel";

/** 미리보기 확인 모달에 실을 한 턴 금액을 **요청 시점**의 모델 목록 캐시에서 읽는다. 렌더 때 잡은 값을 쓰면, 가격 바뀜을
 * 확인하고 다시 보낸 요청이 이어서 하루 한 번 확인을 받을 때 그 모달이 옛 가격을 말한다 — 같은 클로저가 두 번 불리기
 * 때문이다.
 *
 * 가격 바뀜 거절이면 모델 목록을 다시 받은 뒤 읽는다(그 모달의 금액은 서버가 실은 값이지만, 뒤이은 확인과 부족 안내가 새
 * 가격을 읽어야 한다). 다시 받기가 실패해도 던지지 않는다 — 캐시의 값으로 묻고, 목록이 없으면 확인 문구가 숫자 없이 말한다. */
export async function previewConfirmTurnCost(
  queryClient: QueryClient,
  error: unknown,
  modelId: ChatModelId,
): Promise<number | undefined> {
  if (isCloverPriceChangedError(error)) await queryClient.refetchQueries({ queryKey: chatModelKeys.all });
  return previewTurnCost(queryClient.getQueryData<ChatModel[]>(chatModelKeys.all), modelId);
}
