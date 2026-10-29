import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { FileQuestion } from "lucide-react";
import { useRef, useState } from "react";

import { useRecentChatRoomListQuery } from "@/entities/chat-room";
import { useAttendanceBoardQuery, useCloverPricingQuery, type AttendanceBoard as AttendanceBoardData } from "@/entities/clover";
import { useSessionQuery } from "@/entities/session";
import { isApiError } from "@/shared/api/client";

import { toAttendanceView, type AttendanceView } from "../model/attendanceView";
import type { ClaimFocusTarget } from "../model/claimFocus";
import { formatGuestTotal, formatNextSpecialSentence, formatProgress, RETURNING_SENTENCE } from "../model/attendanceCopy";
import { toKstDateKey } from "../model/returningVisitor";
import { useAttendanceClaim } from "../model/useAttendanceClaim";
import { AttendanceBoard, AttendanceBoardSkeleton } from "./AttendanceBoard";
import { AttendanceClaimArea } from "./AttendanceClaimArea";
import { AttendanceGuide } from "./AttendanceGuide";

// 판은 카드 그리드형 목록이 아니라 한 덩어리 상세라 좁은 컬럼이다. 판을 감싸는 카드는 두지 않는다 — 칸이 이미 카드
// 표면이라 겹치면 카드 안 카드가 된다.
const PAGE_CLASS = "mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-10 sm:px-6 lg:pt-6";

/** `/attendance` — 출석판 "또 만나, 28일". 하루 한 번 받는 칸 28개짜리 누적 진도판이다(하루 쉬어도 끊기지 않는다).
 *
 * 비로그인도 들어와 공개 보상표로 판을 보고 거기서 로그인을 권한다. 무엇을 그릴지는 `toAttendanceView` 가 정하고, 출석
 * 스위치가 꺼져 있으면 노벨 목록처럼 이 자리에 찾을 수 없는 화면을 그린다(페이지끼리 가져다 쓸 수 없어 같은 모양을
 * 여기 둔다). */
export function AttendancePage() {
  const pricing = useCloverPricingQuery();
  const session = useSessionQuery();
  const isLoggedIn = session.data !== undefined;
  // 가격을 못 받았으면 꺼짐으로 보지 않고 서버 판 응답에 맡긴다 — 판정 규칙은 `toAttendanceView` 머리 주석.
  const shouldLoadBoard = pricing.data?.attendance?.enabled ?? pricing.isError;
  const boardQuery = useAttendanceBoardQuery({ enabled: isLoggedIn && shouldLoadBoard });

  const [justClaimedSeq, setJustClaimedSeq] = useState<number | null>(null);
  // 수령 결과로 포커스가 있던 자리가 사라졌을 때 옮겨 갈 곳. 그 자리가 그려지는 첫 렌더에서 한 번만 쓰고 비운다 — 그 사이 다른
  // 자리가 몇 번 다시 그려져도 엉뚱한 곳이 포커스를 가져가지 않게 대상을 함께 적어 둔다.
  const pendingFocusRef = useRef<ClaimFocusTarget | null>(null);
  const focusRef = (target: ClaimFocusTarget) => (node: HTMLElement | null) => {
    if (node && pendingFocusRef.current === target) {
      pendingFocusRef.current = null;
      node.focus({ preventScroll: true });
    }
  };
  const { flow, claim } = useAttendanceClaim({
    onGranted: (board) => setJustClaimedSeq(lastClaimedSeq(board)),
    onFocusMove: (target) => {
      pendingFocusRef.current = target;
    },
  });

  const view = toAttendanceView({
    pricing: {
      isPending: pricing.isPending,
      isError: pricing.isError,
      attendanceEnabled: pricing.data?.attendance?.enabled,
      rewards: pricing.data?.attendance?.rewards,
    },
    session: {
      isPending: session.isPending,
      isLoggedIn,
      identityVerified: session.data?.identityVerified ?? false,
    },
    board: {
      isPending: boardQuery.isPending,
      failureCount: boardQuery.failureCount,
      isNotFound: isApiError(boardQuery.error) && boardQuery.error.status === 404,
      data: boardQuery.data,
    },
    claim: flow,
    todayKst: toKstDateKey(new Date()),
  });
  // "대화 이어가기" 는 판 화면의 받은 뒤 자리에만 있어, 판이 그려질 때만 최근 대화방을 묻는다(꺼짐·비로그인·찾을 수 없음 화면은
  // 묻지 않는다). 대화방 쿼리는 보는 사람이 없으면 꺼진다.
  const recentRooms = useRecentChatRoomListQuery(view.kind === "board" ? session.data?.id : undefined);

  if (view.kind === "notFound") return <AttendanceNotFound />;

  return (
    <main className={PAGE_CLASS}>
      {/* 스켈레톤은 출석 스위치를 아직 모르는 때다 — 꺼진 서버에서 가격 요청이 늦거나 재시도하는 동안 출석판 문구가 보이지
          않게, 기능 유무를 말하지 않는 막대만 그린다. */}
      {view.kind === "skeleton" ? (
        <div className="flex flex-col gap-2" aria-hidden>
          <div className="h-8 w-44 animate-pulse rounded bg-secondary" />
          <div className="h-5 w-64 max-w-full animate-pulse rounded bg-secondary" />
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold tracking-tight text-balance text-foreground">또 만나, 28일</h1>
          <p className="text-sm break-keep text-muted-foreground">하루 쉬어도 괜찮아요. 출석한 만큼 선물이 쌓여요.</p>
        </div>
      )}
      <AttendanceBody
        view={view}
        justClaimedSeq={justClaimedSeq}
        recentRoomId={recentRooms.data?.[0]?.id}
        focusRef={focusRef}
        onClaim={(board) => claim(board.lastClaimedOn)}
        onRetryLoad={() => void boardQuery.refetch()}
      />
      {view.kind !== "skeleton" && <AttendanceGuide minValidDays={pricing.data?.attendance?.minValidDays} />}
    </main>
  );
}

function lastClaimedSeq(board: AttendanceBoardData): number | null {
  const claimed = board.cells.filter((cell) => cell.status === "claimed");
  return claimed[claimed.length - 1]?.seq ?? null;
}

function AttendanceBody({
  view,
  justClaimedSeq,
  recentRoomId,
  focusRef,
  onClaim,
  onRetryLoad,
}: {
  view: Exclude<AttendanceView, { kind: "notFound" }>;
  justClaimedSeq: number | null;
  recentRoomId: string | undefined;
  focusRef: (target: ClaimFocusTarget) => (node: HTMLElement | null) => void;
  onClaim: (board: AttendanceBoardData) => void;
  onRetryLoad: () => void;
}) {
  switch (view.kind) {
    case "skeleton":
      return <AttendanceBoardSkeleton />;
    case "guest":
      return (
        <>
          <p className="text-sm font-semibold text-foreground">{formatGuestTotal(view.rewards)}</p>
          <AttendanceBoard
            cells={view.rewards.map((amount, index) => ({ seq: index + 1, amount, status: "upcoming" }))}
            justClaimedSeq={null}
          />
          <Button asChild size="lg" className="h-11 w-full self-start sm:w-auto">
            <Link to="/login" search={{ redirect: "/attendance" }}>
              로그인하고 출석 시작하기
            </Link>
          </Button>
        </>
      );
    case "loadFailed":
      return (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-muted-foreground">출석판을 불러오지 못했어요.</p>
          <Button type="button" variant="outline" onClick={onRetryLoad}>
            다시 시도
          </Button>
        </div>
      );
    case "board": {
      const { board } = view;
      const claimedCount = board.cells.filter((cell) => cell.status === "claimed").length;
      const nextSpecial = formatNextSpecialSentence(board);
      return (
        <>
          <div className="flex flex-col gap-1">
            {view.isReturning && <p className="mb-1 text-sm break-keep text-foreground">{RETURNING_SENTENCE}</p>}
            <div className="flex flex-col gap-1 sm:flex-row sm:flex-wrap sm:items-baseline sm:justify-between sm:gap-x-4">
              <p className="text-sm font-semibold text-foreground">{formatProgress(claimedCount)}</p>
              {nextSpecial !== null && <p className="text-xs text-muted-foreground">{nextSpecial}</p>}
            </div>
          </div>
          <AttendanceBoard cells={board.cells} justClaimedSeq={justClaimedSeq} />
          <AttendanceClaimArea
            area={view.claimArea}
            todayCell={board.cells.find((cell) => cell.status === "today")}
            onClaim={() => onClaim(board)}
            recentRoomId={recentRoomId}
            isJustClaimed={justClaimedSeq !== null}
            focusRef={focusRef}
          />
        </>
      );
    }
  }
}

/** 출석 스위치가 꺼졌을 때. 진입점(메뉴·홈 카드)도 숨어 있어 주소로 들어온 사람에게도 출석판이 없는 것과 같다. */
function AttendanceNotFound() {
  return (
    <main className={PAGE_CLASS}>
      <div className="flex flex-col items-center gap-3 px-6 py-16 text-center break-keep">
        <FileQuestion aria-hidden className="size-8 text-muted-foreground" />
        <h1 className="text-lg font-semibold text-foreground">페이지를 찾을 수 없어요</h1>
        <p className="text-sm text-muted-foreground">주소가 잘못됐거나 사라진 페이지예요.</p>
        <Button asChild className="mt-3">
          <Link to="/">홈으로</Link>
        </Button>
      </div>
    </main>
  );
}
