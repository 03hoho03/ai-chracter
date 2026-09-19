/** clover-techspec.md CT-16 (clover-goal-prompt.md CL-25·CL-27) — 잔량을 **언제** 보여주고
 * **어떤 잉크**로 칠할지. 렌더가 아니라 판정이라 여기 순수 함수로 둔다(이 앱의 FE 테스트는
 * 전부 `model/`의 순수 함수다 — `renderHook`·`@testing-library/react` 선례 0건).
 *
 * 🔴 `text-primary`는 **잉크**이지 솔리드 채움이 아니다. DESIGN.md §2 밝기 예산 규칙이 "화면당
 * 하나"로 관리하는 것은 `primary` **솔리드 채움**이고(채팅=전송 버튼, 이미지=생성 버튼), 잉크는
 * 그 예산을 쓰지 않는다 — 같은 문서가 `text-primary`의 대비 대역(5.78~7.18:1)을 별도로 적어
 * 두고 `MyPagePage`·`StoryDetailBody`가 문장 속에서 이미 쓴다. 그래서 부족 상태를 primary로
 * 칠해도 전송/생성 버튼과 경합하지 않는다. */

/** 무료 한도를 아직 안 쓴 사용자에게는 잔량이 보이지 않는다(CL-25 "필요할 때만 노출").
 *
 * 판정 근거로 `spendConfirmedToday`를 쓰는 이유: FE는 "무료 일일분이 남았는가"를 직접 알 수
 * 없다(`GET /me/clover`는 잔액·오늘 확인 여부·출석 가능만 준다). 확인 모달은 **소진 시점에만**
 * 뜨므로, 오늘 확인했다는 사실이 곧 "오늘 무료분을 다 썼다"는 뜻이다 — 소진 시점 이후에만
 * 참이 되는 유일한 서버 신호다.
 *
 * `hasCloverShortage`는 그보다 앞선다 — 잔액까지 바닥나 429를 받은 직후에는 확인 기록 여부와
 * 무관하게 보여야 한다(확인 전에 잔액이 0일 수 있다). */
export function shouldShowCloverBalance({
  spendConfirmedToday,
  hasCloverShortage,
}: {
  spendConfirmedToday: boolean;
  hasCloverShortage: boolean;
}): boolean {
  return spendConfirmedToday || hasCloverShortage;
}

/** 잔액이 **다음 한 번을 못 내는** 상태. `balance < cost`이지 `balance === 0`이 아니다 —
 * 이미지 1장이 30인데 잔액이 10이면 0이 아니어도 못 쓴다(clover-goal-prompt.md CL-11).
 *
 * `cost`를 인자로 받는 이유: 같은 잔액이 채팅(10)에서는 충분하고 이미지(30)에서는 부족할 수
 * 있어, 표면마다 답이 다르다. */
export function isCloverInsufficient(balance: number, cost: number): boolean {
  return balance < cost;
}
