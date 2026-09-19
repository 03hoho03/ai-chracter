import { useEffect, useRef } from "react";

import { useClaimAttendanceMutation } from "./useClaimAttendanceMutation";
import { useCloverBalanceQuery } from "./useCloverBalanceQuery";

/** clover-techspec.md CT-10 — 출석 지급의 **호출 자리**다.
 *
 * 🔴 `GET /me/clover`에 부작용을 두지 않기로 했으므로(전용 POST), **FE가 부르는 걸 빠뜨리면
 * 아무도 출석분을 못 받는다.** 컴파일도 테스트도 그 누락을 잡지 못한다 — 실제로 한동안
 * 호출부가 0건이었고 브라우저 실검증(S12 D-1)에서야 드러났다. 지금 호출부는
 * `widgets/clover-attendance`의 `CloverAttendanceMount` **하나**이고, 그게
 * `routes/__root.tsx`에 마운트된다(비로그인 가드도 거기 있다 — 이 훅은 로그인 상태를 모른다).
 *
 * **멱등은 서버가 보장한다** — `users.clover_attendance_granted_on`이 오늘(KST)이면 `granted=false`로
 * 돌려주고 아무것도 하지 않는다(원장 유니크 제약이 동시 요청까지 막는다, clover-goal-prompt.md CL-8).
 * 그래서 여러 번 불러도 안전하고 `useEffect` 경합이 돈 문제가 되지 않는다.
 *
 * 그럼에도 `hasClaimedRef`를 두는 이유는 **요청 수**다 — 이 가드가 없으면 invalidate → 재조회 →
 * `attendanceClaimable`이 아직 true → 다시 POST 로 마운트당 여러 번 나간다. 서버가 매번
 * `granted=false`로 막으므로 잔액은 틀어지지 않는다.
 *
 * 🔴 그래서 래치는 **성공에서만** 닫는다. `mutate()` 앞에서 닫으면 POST 가 한 번 실패한 뒤로는
 * 래치가 거짓으로 "받았다"를 말해, 그 마운트에서 `claimable`이 다시 true 가 되어도(예: 자정을
 * 넘긴 탭, 재조회) 두 번 다시 시도하지 않는다. 뮤테이션 기본 재시도는 0 이고(`query-core`의
 * `retry: this.options.retry ?? 0` — 쿼리의 `?? 3`과 다르다) 이 훅도 미설정이라, 실패는 토스트도
 * 로그도 없이 조용하다. **출석은 유저가 클로버를 받는 유일한 자동 경로**라 그 조용한 포기가 비싸다.
 *
 * ⚠️ 의존성을 `[claimable, mutate]`로 두는 것이 이 배치의 짝이다 — `isPending`을 넣으면 실패
 * 직후 effect 가 다시 돌고 래치가 아직 열려 있어 **무한 재시도**가 된다. 지금은 실패해도 effect 가
 * 다시 돌지 않으므로, 다음 시도는 `claimable`이 다시 바뀌거나 다음 마운트에서 일어난다. */
export function useCloverAutoAttendance(): void {
  const { data } = useCloverBalanceQuery();
  const claimAttendance = useClaimAttendanceMutation();
  const hasClaimedRef = useRef(false);

  const claimable = data?.attendanceClaimable ?? false;
  const { mutate } = claimAttendance;

  useEffect(() => {
    if (!claimable || hasClaimedRef.current) return;
    mutate(undefined, {
      onSuccess: () => {
        hasClaimedRef.current = true;
      },
    });
  }, [claimable, mutate]);
}
