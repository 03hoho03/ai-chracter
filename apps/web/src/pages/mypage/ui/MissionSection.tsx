import { Button } from "@ai-character-chat/ui/components/button";
import { useLocation } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import {
  CLOVER_MISSION_LABELS,
  CLOVER_MISSIONS_SECTION_ID,
  projectCloverMissionState,
  useClaimCloverMissionMutation,
  useCloverMissionsQuery,
  type CloverMissionItem,
} from "@/entities/clover";
import { isIdentityVerificationRequiredError } from "@/entities/identity";
import type { MeResponse } from "@/entities/session";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";
const IDENTITY_REQUIRED_MESSAGE = "본인인증을 하면 받을 수 있어요.";

/** 미션 수령 실패 토스트. 본인인증 403 은 실패가 아니라 "아직 받을 수 없다"라 오류 토스트가 아니고, 세션은 전역
 * 뮤테이션 처리가 다시 읽어 행의 "받기"가 상태 배지로 바뀐다. */
function toastClaimError(error: unknown) {
  if (isIdentityVerificationRequiredError(error)) {
    toast(IDENTITY_REQUIRED_MESSAGE);
    return;
  }
  toast.error(GENERIC_ERROR_MESSAGE);
}

/** 클로버 미션. 충전 화면이 로그인 없이 열리는 상품 안내가 되면서, 회원만의 일인 미션 보상 받기는 계정 설정 화면으로
 * 왔다. 충전 화면의 "미션 보상 받기" 링크가 이 섹션 앵커로 바로 온다(`scroll-mt-20` 은 sticky 헤더 높이만큼 띄운다).
 *
 * 본인인증 전이라 받을 수 없다는 안내는 따로 두지 않는다 — 같은 화면의 본인인증 섹션이 "무료 대화와 미션 클로버를
 * 받으려면 본인인증이 필요하다"를 이미 말하고, 그 안내의 "본인인증하기" 링크는 이 화면 자신으로 돌아온다. 행에서는
 * 누르면 403 이 올 "받기" 대신 상태 배지를 둔다. */
export function MissionSection({ me }: { me: MeResponse }) {
  const { data, isPending } = useCloverMissionsQuery();
  const claimMission = useClaimCloverMissionMutation();
  const isClaimLocked = me.identityGated;
  const sectionRef = useScrollToMissionsOnArrival(data !== undefined);

  const handleClaim = (key: string) => {
    if (claimMission.isPending) return;
    claimMission.mutate(key, {
      onSuccess: (res) => {
        toast.success(res.granted ? "미션 보상을 받았어요." : "이미 받은 미션이에요.");
      },
      onError: toastClaimError,
    });
  };

  return (
    <section ref={sectionRef} id={CLOVER_MISSIONS_SECTION_ID} className="flex scroll-mt-20 flex-col gap-4">
      <h2 className="text-xl font-semibold tracking-tight text-foreground">미션</h2>
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
              isClaimLocked={isClaimLocked}
              onClaim={() => handleClaim(mission.key)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/** 충전 화면의 "미션 보상 받기"(`#clover-missions`)로 들어오면, 미션 목록이 그려진 뒤 한 번 이 섹션으로 스크롤한다. 라우터의
 * 해시 이동은 첫 렌더에 일어나는데, 그때는 위쪽 섹션(본인인증 등)과 이 목록이 아직 불러오는 중이라 높이가 늘면서 섹션이
 * 아래로 밀린다. 한 번만 옮긴다 — 그 뒤 사용자가 스크롤한 자리를 빼앗지 않는다. */
function useScrollToMissionsOnArrival(isReady: boolean) {
  const hash = useLocation({ select: (location) => location.hash });
  const sectionRef = useRef<HTMLElement>(null);
  const hasScrolled = useRef(false);

  useEffect(() => {
    if (!isReady || hasScrolled.current || hash !== CLOVER_MISSIONS_SECTION_ID) return;
    // 옮겼다는 표시는 실제로 옮길 때 남긴다 — StrictMode 가 effect 를 정리하고 다시 돌리면 정리에서 취소된 첫 프레임 대신
    // 둘째 실행이 옮겨야 한다.
    const frame = requestAnimationFrame(() => {
      hasScrolled.current = true;
      sectionRef.current?.scrollIntoView({ block: "start" });
    });
    return () => cancelAnimationFrame(frame);
  }, [isReady, hash]);

  return sectionRef;
}

type MissionRowProps = {
  mission: CloverMissionItem;
  isClaiming: boolean;
  /** 본인인증 전이라 달성한 미션도 받을 수 없다. 누르면 403 이 올 버튼 대신 상태 배지를 둔다. */
  isClaimLocked: boolean;
  onClaim: () => void;
};

function MissionRow({ mission, isClaiming, isClaimLocked, onClaim }: MissionRowProps) {
  const state = projectCloverMissionState(mission);
  const label = CLOVER_MISSION_LABELS[mission.key] ?? mission.key;

  return (
    <li className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">클로버 {mission.reward.toLocaleString()}개</span>
      </div>
      {/* DESIGN.md The Brightness Budget Rule — primary 솔리드 채움은 화면당 하나다. 미션은 여러 개가
          동시에 달성될 수 있어 solid면 솔리드 핑크가 한꺼번에 여러 개 뜨므로, 여기는 outline이다. */}
      {state === "claimable" && isClaimLocked && (
        <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
          본인인증 후 받기
        </span>
      )}
      {state === "claimable" && !isClaimLocked && (
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
