/**
 * 이 화면 하나가 읽는 자격 목록과, 실효 경로를 정하는 서버 스위치. 모든 자격 쓰기가 `all` 접두 하나로 둘을 함께 무효화한다 — 스위치
 * 조회는 값싼 요청이고 서버를 다시 띄운 직후 값을 빨리 따라간다. 스위치는 기능 스위치 화면도 같은 요청으로 읽지만 키를 나눈다: 그
 * 화면의 키 모양이 바뀌어도 이 화면이 조용히 다른 캐시를 읽지 않게 하고, 같은 키 배열을 두 곳에 손으로 적지 않는다.
 */
export const llmCredentialKeys = {
  all: ["llmCredentials"] as const,
  list: () => [...llmCredentialKeys.all, "list"] as const,
  runtimeSwitch: () => [...llmCredentialKeys.all, "runtimeSwitch"] as const,
};
