/**
 * 초안 저장 뮤테이션의 옵션. 같은 초안의 저장을 한 큐(`scope`)에 넣어 **앞 저장이 끝나야 다음 저장을 보낸다**.
 *
 * 순서를 묶지 않으면 두 가지 자리에서 저장이 겹친다. 자동저장 디바운스는 앞 저장의 응답을 기다리지 않고, 오프라인에서 멈춘
 * 저장들은 다시 연결될 때 한꺼번에 재개된다(큐가 없는 뮤테이션은 모두 동시에 `continue` 된다). 겹친 두 PATCH 는 서버에서
 * 같은 옛 값을 읽고, 값이 바뀌었다고 본 쪽만 쓰므로 중간 값이 남을 수 있다. 다른 칸은 다음 저장이 전체 값을 다시 실어
 * 고쳐지지만, 소설 만들기 허락처럼 "바뀌었을 때만 싣는" 칸은 다시 실리지 않아 어긋난 채로 남는다.
 *
 * 큐로 묶은 대가로 응답이 오지 않는 요청 하나가 그 초안의 뒤 저장(발행 직전 저장 포함)을 모두 붙잡는다. 그래서 저장마다 시간
 * 제한을 두고, 넘기면 요청을 끊어 실패로 끝낸다 — 큐가 풀리고, 실패한 저장은 호출부의 실패 경로를 그대로 탄다.
 */
export const CONTENT_DRAFT_SAVE_TIMEOUT_MS = 30_000;

/** 같은 초안끼리만 줄을 세우는 큐 이름. 다른 초안의 저장은 서로 기다리지 않는다. */
export function contentDraftSaveScopeId(draftKey: string) {
  return `content-draft-save:${draftKey}`;
}

export function contentDraftSaveOptions<TVariables, TData>(
  request: (variables: TVariables, signal: AbortSignal) => Promise<TData>,
  draftKey: string,
) {
  return {
    mutationFn: async (variables: TVariables) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), CONTENT_DRAFT_SAVE_TIMEOUT_MS);
      try {
        return await request(variables, controller.signal);
      } finally {
        clearTimeout(timer);
      }
    },
    scope: { id: contentDraftSaveScopeId(draftKey) },
  };
}
