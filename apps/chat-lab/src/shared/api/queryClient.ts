import { QueryClient } from "@tanstack/react-query";

/**
 * 앱 하나에 하나뿐인 쿼리 캐시. 프로바이더 밖(호스팅 묶음 로더 — 상세·턴·지표를 읽는 함수가 목록·묶음 캐시를 읽고 쓴다)에서도 같은
 * 캐시를 써야 해서 여기 둔다.
 */
export const queryClient = new QueryClient();
