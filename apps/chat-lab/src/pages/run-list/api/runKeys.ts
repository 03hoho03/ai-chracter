/** 런 목록 캐시 키. 목록을 새로 훑은 결과도 이 키에 바로 넣는다. */
export const runKeys = {
  all: ["runs"] as const,
  list: () => [...runKeys.all, "list"] as const,
};
