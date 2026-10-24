import type { QueryClient } from "@tanstack/react-query";

import { chatModelKeys } from "@/entities/chat-model";
import { sessionKeys } from "@/entities/session";

/** 상위 모델 허용이 없다는 403 을 받은 뒤 세션과 모델 목록을 다시 읽게 한다. 허용을 거둔 직후의 탭은 옛 세션으로 모델 칩을,
 * 옛 목록으로 상위 모델을 계속 보이므로 이 응답을 계기로 둘 다 거둔다. 대화방 저장과 미리보기 시작이 같은 일을 하므로
 * 한 함수로 둔다. */
export function invalidateChatModelAccess(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
  void queryClient.invalidateQueries({ queryKey: chatModelKeys.all });
}
