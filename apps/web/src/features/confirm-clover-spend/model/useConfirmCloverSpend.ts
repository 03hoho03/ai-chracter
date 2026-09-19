import { useQueryClient } from "@tanstack/react-query";

import {
  cloverBalanceQueryOptions,
  isCloverSpendConfirmRequired,
  useConfirmCloverSpendMutation,
} from "@/entities/clover";
import type { CloverSpendConfirmOutcome } from "@/entities/clover";

import { ConfirmCloverSpendModal } from "../ui/ConfirmCloverSpendModal";

/** 오류 하나를 받아 **무엇을 할지**를 돌려준다(clover-goal-prompt.md CL-19).
 *
 * 반환값의 세 갈래는 `entities/clover`의 `CloverSpendConfirmOutcome`에 있다 — 🔴 불리언이었을 때
 * **"그만두기"가 실패와 구분되지 않아** 세 호출부가 전부 *"응답 생성에 실패했습니다"* 를
 * 띄웠다(S12 C-3). 실패한 것이 없는데도.
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
 * ⚠️ 동의 POST가 실패하면 **재시도하지 않는다**(`unhandled`). 성공을 가정하고 다시 보내면 BE가
 * 또 `CLOVER_CONFIRM_REQUIRED`를 내고, 호출부의 차단기가 없었다면 그대로 루프가 된다. */
export function useConfirmCloverSpend(): (
  error: unknown,
  cost: number,
) => Promise<CloverSpendConfirmOutcome> {
  const queryClient = useQueryClient();
  const { mutateAsync } = useConfirmCloverSpendMutation();

  return async function confirmCloverSpend(error, cost) {
    if (!isCloverSpendConfirmRequired(error)) return "unhandled";

    const balance = await queryClient
      .ensureQueryData(cloverBalanceQueryOptions)
      .then((data) => data.balance)
      .catch(() => 0);

    // 🔴 여기가 `declined`다 — 모달이 `false`를 돌려준 것은 **사용자의 선택**이지 실패가 아니다.
    if (!(await ConfirmCloverSpendModal.call({ balance, cost }))) return "declined";

    try {
      // 성공하면 이 뮤테이션의 `onSuccess`가 잔액을 invalidate 한다(사본을 두지 않는다).
      await mutateAsync();
    } catch {
      // 동의를 서버에 남기지 못했으면 재시도는 같은 429를 받는다 — 여기서 멈추는 쪽이 정직하다.
      // 이건 진짜 실패라 `declined`가 아니라 `unhandled`다(호출부가 오류를 보여 줘야 한다).
      return "unhandled";
    }
    return "retry";
  };
}
