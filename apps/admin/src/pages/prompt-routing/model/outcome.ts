import type { AdminPromptRoutingResponse } from "@/entities/prompt-routing";

import type { RouteSaveFailure } from "./routeErrors";

/** 저장·되돌리기 확인 모달이 페이지에 돌려주는 결과. 취소는 `undefined` 다. 그 밖·네트워크 실패는 모달이 열린 채 다시 누를 수
 * 있게 모달 안에서 끝내고 여기로 오지 않는다. */
export type RoutingOutcome =
  | { status: "saved"; data: AdminPromptRoutingResponse }
  | { status: "failed"; failure: Exclude<RouteSaveFailure, { kind: "other" }> };
