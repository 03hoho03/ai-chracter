import { useCloverAutoAttendance } from "@/entities/clover";
import { useSessionQuery } from "@/entities/session";

/** clover-techspec.md CT-10 — 일일 출석 지급의 **유일한 호출 자리**.
 *
 * 🔴 `useCloverAutoAttendance`는 만들어만 두고 아무도 부르지 않아 **출석분이 한 번도 지급되지
 * 않았다**(S12 D-1, 브라우저 실검증). `GET /me/clover`에 부작용이 없고(전용 POST) 컴파일도
 * 테스트도 "아무도 안 부른다"를 잡지 못하므로, 훅 옆에 호출부를 만들어 `__root.tsx`에 한 번
 * 마운트한다.
 *
 * **왜 위젯인가** — 훅이 부르는 `useCloverBalanceQuery`에는 `enabled`가 없어 비로그인에서
 * 마운트되면 `GET /me/clover`가 401로 떨어진다. 그 가드에는 세션이 필요한데
 * `entities/clover`가 `entities/session`을 import 할 수 없으므로(같은 레이어 슬라이스 간 직접
 * import 금지, `apps/web/CLAUDE.md` §아키텍처) 둘을 **합성하는 자리**가 따로 있어야 한다.
 * `widgets/reconsent-legal`이 이미 같은 모양이다 — 루트에 상시 마운트되고, 세션을 스스로 읽어
 * 할 일이 있을 때만 움직인다.
 *
 * 🔴 **두 컴포넌트로 쪼갠 것은 Rules of Hooks 때문이다.** `if (!me) return null` 뒤에
 * `useCloverAutoAttendance()`를 두면 로그인 전후로 훅 개수가 달라진다. 바깥이 판정하고
 * 안쪽이 훅을 부른다.
 *
 * **요청 수**: 로그인 사용자의 앱 로드당 `GET /me/clover` 1건이 는다. 다만 잔액을 읽는 세 화면
 * (`ChatRoomView`·`GenerateImagesPromptField`·`MyPagePage`)이 같은 쿼리 키를 공유하므로
 * `staleTime: 30_000` 안에서는 그쪽 조회가 캐시로 붙는다. 출석 POST 는 성공 시 훅의 래치가
 * 닫아 마운트당 1회이고, 서버는 그와 별개로 KST 날짜 멱등키로 하루 1회를 보장한다. */
export function CloverAttendanceMount() {
  const { data: me } = useSessionQuery();
  return me ? <CloverAttendanceEffect /> : null;
}

function CloverAttendanceEffect() {
  useCloverAutoAttendance();
  return null;
}
