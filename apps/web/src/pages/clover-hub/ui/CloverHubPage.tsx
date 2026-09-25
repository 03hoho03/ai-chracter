import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";

import {
  CLOVER_EXPIRY_NOTICE_MESSAGE,
  CLOVER_MISSION_LABELS,
  CloverBalance,
  formatCloverExpiringSoonMessage,
  projectCloverMissionState,
  useClaimAttendanceMutation,
  useClaimCloverMissionMutation,
  useCloverBalanceQuery,
  useCloverMissionsQuery,
  type CloverMissionItem,
} from "@/entities/clover";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

/** 클로버 허브 페이지.
 *
 * 컨테이너 폭은 마이페이지(`pages/mypage/ui/MyPagePage.tsx:56`)와 같은 `max-w-md`다 —
 * 진입점이 마이페이지라 폭이 이어지면 이동이 자연스럽다.
 */
export function CloverHubPage() {
  return (
    <main className="mx-auto flex max-w-md flex-col gap-10 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">클로버</h1>
        {/* "클로버 페이지·내역 화면에도 상시 고지를 둔다."
            문구는 entities/clover의 단일 소스(cloverExpiryNotice.ts)를 쓴다 — 내역 화면과
            리터럴을 각자 복사해 갖고 있다가 "7일"과 게시된 공지("7~8일")가 어긋났던 전례가
            있다. */}
        <p className="text-sm break-keep text-muted-foreground">{CLOVER_EXPIRY_NOTICE_MESSAGE}</p>
      </div>

      <BalanceSection />
      <AttendanceSection />
      <MissionSection />
    </main>
  );
}

function SectionHeading({ children }: { children: string }) {
  return <h2 className="text-xl font-semibold tracking-tight text-foreground">{children}</h2>;
}

function BalanceSection() {
  const { data, isPending } = useCloverBalanceQuery();
  // 3일 임박 게이트는 BE가 이미 걸었다. FE는 그 값을
  // D-day 문구로만 바꾼다(재판정하지 않는다).
  const expiringMessage = data ? formatCloverExpiringSoonMessage(data.expiringSoon, new Date()) : null;

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>현재 잔액</SectionHeading>
      <div className="flex flex-col gap-1.5">
        {isPending ? (
          <span className="text-sm text-muted-foreground">불러오는 중…</span>
        ) : (
          <CloverBalance balance={data?.balance ?? 0} className="text-sm" />
        )}
        {/* 평소 무채색, 만료 임박일 때만 primary 잉크(솔리드
            채움이 아니다 — 밝기 예산은 화면당 솔리드 채움 하나만 관리한다, `CloverBalance`의
            같은 처방). */}
        {expiringMessage && <p className="text-sm text-primary">{expiringMessage}</p>}
      </div>
      {/* 내역 화면 진입점. `pages/mypage/ui/MyPagePage.tsx`의
          "내 작품" 링크와 같은 관용구(`font-medium ... text-primary hover:underline
          focus-visible:underline`). */}
      <Link
        to="/clover/history"
        className="w-fit text-sm font-medium whitespace-nowrap text-primary hover:underline focus-visible:underline"
      >
        내역 보기
      </Link>
    </section>
  );
}

function AttendanceSection() {
  const { data } = useCloverBalanceQuery();
  const claimAttendance = useClaimAttendanceMutation();
  const claimable = data?.attendanceClaimable ?? false;

  const handleClaim = () => {
    // apps/web/CLAUDE.md §포커스 — 로딩 중 재클릭을 막는 건 `disabled`가 아니라 핸들러
    // early return이다(WithdrawAccountDialog 선례와 같은 처방).
    if (claimAttendance.isPending) return;
    claimAttendance.mutate(undefined, {
      onSuccess: (res) => {
        // 자동 지급이 사라진 뒤 처음으로 성공·실패가
        // 화면에 보여야 한다. `granted: false`는 오류가 아니라 "오늘 이미 받았다"는 정상
        // 응답이다(useClaimAttendanceMutation 주석과 같은 규칙).
        toast.success(res.granted ? "출석체크를 완료했어요." : "오늘은 이미 출석을 확인했어요.");
      },
      onError: () => {
        toast.error(GENERIC_ERROR_MESSAGE);
      },
    });
  };

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>출석체크</SectionHeading>
      {claimable ? (
        <Button
          onClick={handleClaim}
          aria-disabled={claimAttendance.isPending}
          className="w-fit aria-disabled:pointer-events-none aria-disabled:opacity-65"
        >
          {claimAttendance.isPending ? "확인 중..." : "출석체크"}
        </Button>
      ) : (
        <p className="text-sm text-muted-foreground">오늘 출석을 이미 확인했어요.</p>
      )}
    </section>
  );
}

function MissionSection() {
  const { data, isPending } = useCloverMissionsQuery();
  const claimMission = useClaimCloverMissionMutation();

  const handleClaim = (key: string) => {
    if (claimMission.isPending) return;
    claimMission.mutate(key, {
      onSuccess: (res) => {
        toast.success(res.granted ? "미션 보상을 받았어요." : "이미 받은 미션이에요.");
      },
      onError: () => {
        toast.error(GENERIC_ERROR_MESSAGE);
      },
    });
  };

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>미션</SectionHeading>
      {isPending ? (
        <span className="text-sm text-muted-foreground">불러오는 중…</span>
      ) : (
        <ul className="flex flex-col gap-3">
          {data?.missions.map((mission) => (
            <MissionRow
              key={mission.key}
              mission={mission}
              // 셋 중 지금 청구 중인 것만 로딩 문구를 보여준다 — `variables`는 마지막으로
              // 호출된 인자를 들고 있다(tanstack-query 관례).
              isClaiming={claimMission.isPending && claimMission.variables === mission.key}
              onClaim={() => handleClaim(mission.key)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function MissionRow({
  mission,
  isClaiming,
  onClaim,
}: {
  mission: CloverMissionItem;
  isClaiming: boolean;
  onClaim: () => void;
}) {
  const state = projectCloverMissionState(mission);
  const label = CLOVER_MISSION_LABELS[mission.key] ?? mission.key;

  return (
    <li className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">클로버 {mission.reward.toLocaleString()}개</span>
      </div>
      {/* DESIGN.md The Brightness Budget Rule — primary 솔리드 채움은 화면당 하나다. 출석체크
          버튼이 이미 그 자리를 쓰므로(둘 다 solid면 미션이 여러 개 달성됐을 때 솔리드 핑크가
          동시에 여러 개 뜬다), 여기는 outline이다. */}
      {state === "claimable" && (
        <Button
          variant="outline"
          size="sm"
          onClick={onClaim}
          aria-disabled={isClaiming}
          className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
        >
          {isClaiming ? "받는 중..." : "받기"}
        </Button>
      )}
      {/* DESIGN.md Status badges — 중립 상태는 채움이 아니라 외곽선·텍스트다(`bg-muted`는
          카드·모달 위에서 사라진다). */}
      {state === "claimed" && (
        <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
          청구완료
        </span>
      )}
      {state === "unachieved" && (
        <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
          미달성
        </span>
      )}
    </li>
  );
}
