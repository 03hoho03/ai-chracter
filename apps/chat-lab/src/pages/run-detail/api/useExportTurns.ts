import { useMutation, useQueryClient } from "@tanstack/react-query";

import { exportTurns } from "@/shared/api/client";
import { runKeys } from "@/shared/api/runKeys";

/**
 * 로컬 DB 에서 이 런 방의 턴 기록을 런 폴더에 파일로 쓰게 한다. 파일이 생기면 원가·토큰·숨김 스탯·기억 칸이 채워지므로 이 런에
 * 딸린 캐시(상세·턴·지표)를 모두 무효로 만들고, 목록 한 줄(원가·턴 기록 유무)도 바뀌어 목록 캐시도 무효로 만든다.
 */
export function useExportTurns(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (force: boolean) => exportTurns(runId, { force }),
    networkMode: "always",
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: runKeys.run(runId) }),
        queryClient.invalidateQueries({ queryKey: runKeys.list() }),
      ]),
  });
}
