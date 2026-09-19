import { useQueryClient } from "@tanstack/react-query";

import {
  cloverBalanceQueryOptions,
  isCloverSpendConfirmRequired,
  useConfirmCloverSpendMutation,
} from "@/entities/clover";

import { ConfirmCloverSpendModal } from "../ui/ConfirmCloverSpendModal";

/** 오류 하나를 받아 **"재시도해도 되는가"** 를 돌려준다(clover-goal-prompt.md CL-19).
 *
 * `true`면 호출부가 같은 요청을 한 번 더 보내면 된다. `false`면 확인이 필요한 오류가 아니거나
 * (대부분) 사용자가 그만두기를 골랐거나 동의 기록이 실패한 것이므로 호출부는 **평소의 오류
 * 처리를 그대로** 하면 된다.
 *
 * 🔴 **이 훅이 `features`에 있고 호출부에 주입되는 이유**는 FSD다. 트리거는 `features/send-message`
 * 와 `widgets/image-studio` 양쪽에 필요한데, feature가 다른 feature를 import하는 선례가 이
 * 저장소에 0건이다(`.call()` 호출부는 전부 `widgets`/`pages`이거나 같은 슬라이스 안이다).
 * 그래서 두 feature를 **합성하는 위젯**이 이 훅을 만들어 넘긴다.
 *
 * 잔액을 모달에 보여주려면 값이 필요한데 이 시점에는 캐시가 낡았을 수 있어(`staleTime: 30_000`)
 * `ensureQueryData`로 받아 온다 — 이미 신선하면 네트워크를 타지 않는다. 조회가 실패해도 동의
 * 자체는 막지 않는다(잔액은 모달의 부가 정보이고, 정확한 판정은 이미 BE가 했다).
 *
 * ⚠️ 동의 POST가 실패하면 **재시도하지 않는다**(`false`). 성공을 가정하고 다시 보내면 BE가
 * 또 `CLOVER_CONFIRM_REQUIRED`를 내고, 호출부의 차단기가 없었다면 그대로 루프가 된다. */
export function useConfirmCloverSpend(): (error: unknown, cost: number) => Promise<boolean> {
  const queryClient = useQueryClient();
  const { mutateAsync } = useConfirmCloverSpendMutation();

  return async function confirmCloverSpend(error: unknown, cost: number): Promise<boolean> {
    if (!isCloverSpendConfirmRequired(error)) return false;

    const balance = await queryClient
      .ensureQueryData(cloverBalanceQueryOptions)
      .then((data) => data.balance)
      .catch(() => 0);

    if (!(await ConfirmCloverSpendModal.call({ balance, cost }))) return false;

    try {
      // 성공하면 이 뮤테이션의 `onSuccess`가 잔액을 invalidate 한다(사본을 두지 않는다).
      await mutateAsync();
    } catch {
      // 동의를 서버에 남기지 못했으면 재시도는 같은 429를 받는다 — 여기서 멈추는 쪽이 정직하다.
      return false;
    }
    return true;
  };
}
