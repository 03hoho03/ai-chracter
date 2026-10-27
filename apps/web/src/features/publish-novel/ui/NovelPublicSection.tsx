import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ChevronDown, Globe, Loader2 } from "lucide-react";
import { useId, type ReactNode } from "react";
import { toast } from "sonner";

import { useCloverPricingQuery } from "@/entities/clover";
import type { NovelPublicationStatus } from "@/entities/novel";
import { useWebnovelQuery } from "@/entities/webnovel";
import { formatCompactCount } from "@/shared/lib/number/formatCompactCount";

import type { PublishRunResult } from "../api/usePublishNovelRun";
import { isRetryablePublishFailure, toPublishFailureMessage } from "../model/publishFailure";
import { toBuyerPolicyCopy } from "../model/buyerPolicyCopy";
import {
  REVIEW_REQUESTED_MESSAGE,
  toPublicationView,
  toPublicPendingLines,
  toPublishPriceSentence,
  toRejectionNotice,
  type PublicationView,
} from "../model/publicationView";
import { toPublishedPriceRows } from "../model/publishPricing";
import { useNovelPublishActions } from "../model/useNovelPublishActions";
import { MakeChapterFreeModal } from "./MakeChapterFreeModal";
import { PublishNovelModal } from "./PublishNovelModal";
import { WithdrawNovelPublicationModal } from "./WithdrawNovelPublicationModal";

type PublishableNovel = { id: string; chapters: readonly { id: string; ordinal: number }[] };

const BADGE_CLASS = "inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-badge font-medium";

/** 작품 정보(`/novels/$novelId`)의 "노벨 공개" 절 — 행동 줄 아래, 소개 위. 공개 상태(공개 전·공개 중·거둠·운영 조치·
 * 원작 때문에 막힘·첫 공개 승인 대기·반려)와 요청 중("확인 중 · n/N")·요청 실패(심사 장애·상한·낡음), 마지막 심사 거절을 한자리에서 말한다.
 *
 * 카드 껍데기 없이 위 경계선과 제목으로만 갈린다. 이 절의 버튼은 전부 outline·ghost 다 — 이 화면의 솔리드 채움은
 * "이어 읽기" 하나로 남는다. 공개 상태를 못 읽으면(소설화를 쓸 수 없는 계정, 노벨이 꺼져 있음, 일시 실패) 절을 그리지
 * 않는다 — 공개는 이 화면의 주된 일이 아니다. 공개·거두기·무료로 전환 모달은 여기 마운트한다.
 *
 * 노벨 정책 스위치가 켜져 있으면 맨 아래에 "화별 가격" 펼침 목록을 둔다 — 공개한 화 중 앞 화 다음부터 화마다 지금
 * 가격과, 유료 화면 "무료로 전환". 거둠·판매 중단·이용제한 중에도 서버가 전환을 받아 그대로 둔다. 작가 목차는 행
 * 전체가 링크이고 읽기 화면 목차와 함께 쓰는 컴포넌트라 버튼을 넣지 않는다. */
export function NovelPublicSection({ novel }: { novel: PublishableNovel }) {
  const headingId = useId();
  const actions = useNovelPublishActions(novel);
  const status = actions.publication.data;
  const view = status === undefined ? undefined : toPublicationView(status);
  // 좋아요·조회 수는 노벨 작품 정보에만 있다 — 공개 중일 때만 묻는다. 판매가 멈춘 노벨은 게시자에게도 404 라 묻지 않는다.
  const counts = useWebnovelQuery(novel.id, { enabled: view?.kind === "public" && !view.salesStopped }).data;

  if (status === undefined || view === undefined) return null;

  const runState = actions.runState;
  const isChecking = runState.kind === "checking";
  const failureMessage = runState.kind === "failed" ? toPublishFailureMessage(runState.failure) : undefined;
  const rejection =
    !isChecking && status.lastScreening?.outcome === "rejected" ? toRejectionNotice(status.lastScreening) : undefined;

  async function publish() {
    if (status === undefined || isChecking) return;
    actions.clearFailure();
    announcePublishResult(await actions.openPublish(status));
  }

  async function retry() {
    if (isChecking) return;
    announcePublishResult(await actions.retry());
  }

  async function withdraw() {
    if (view === undefined) return;
    const outcome = await actions.openWithdraw(view.kind === "inReview" ? "cancelReview" : "withdraw");
    if (outcome === "cancelled") toast.success("신청을 취소했어요.");
    if (outcome === "withdrawnAfterApproval") toast.success("그사이 승인돼 공개를 거뒀어요.");
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col items-start gap-3 border-t border-border pt-6">
      <PublishNovelModal />
      <WithdrawNovelPublicationModal />
      <MakeChapterFreeModal />
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={headingId} className="text-lg font-semibold text-foreground">
          노벨 공개
        </h2>
        <ViewBadge view={view} />
        {(view.kind === "public" || view.kind === "withdrawn") && view.salesStopped && (
          <span className={cn(BADGE_CLASS, "border-border text-muted-foreground")}>판매 중단</span>
        )}
      </div>

      {isChecking ? (
        // 진행 표시라 동작 줄이기 설정에서도 돈다.
        <div role="status" className="flex flex-col gap-1 text-sm break-keep">
          <p className="flex items-center gap-2 text-foreground tabular-nums">
            <Loader2 aria-hidden className="size-4 animate-spin" />
            공개 전에 내용을 확인하고 있어요 · {runState.current}/{runState.total}
          </p>
          <p className="text-muted-foreground">이 화면을 닫아도 확인을 마친 화까지는 공개돼요.</p>
        </div>
      ) : (
        <ViewBody view={view} status={status} counts={counts} />
      )}

      {rejection !== undefined && (
        <div className="flex flex-col gap-1 text-sm break-keep">
          <p className="text-foreground">{rejection.message}</p>
          {status.screeningRejectionsLeft !== null && (
            <p className="text-muted-foreground tabular-nums">
              오늘 더 확인받을 수 있는 횟수 {status.screeningRejectionsLeft}/{status.screeningRejectionLimit}
            </p>
          )}
        </div>
      )}

      {failureMessage !== undefined && (
        <p role="alert" className="text-sm break-keep text-foreground">
          {failureMessage}
        </p>
      )}

      {!isChecking && (
        <ViewActions
          view={view}
          novelId={novel.id}
          rejectionFixOrdinal={rejection?.fixOrdinal}
          fixChapterId={novel.chapters.find((chapter) => chapter.ordinal === rejection?.fixOrdinal)?.id}
          firstChapterId={novel.chapters.find((chapter) => chapter.ordinal === 1)?.id}
          canRetry={runState.kind === "failed" && isRetryablePublishFailure(runState.failure)}
          onPublish={() => void publish()}
          onRetry={() => void retry()}
          onWithdraw={() => void withdraw()}
        />
      )}

      {!isChecking && <ChapterPriceList novelId={novel.id} status={status} />}
    </section>
  );
}

function announcePublishResult(result: PublishRunResult) {
  if (result === "published") toast.success("노벨에 공개했어요.");
  if (result === "inReview") toast.success(REVIEW_REQUESTED_MESSAGE);
}

/** 심사 대기(첫 공개가 운영자 승인을 기다림)는 게시자가 할 일 없는 기다림이라 거둠과 같은 흐린 잉크, 반려는 읽을
 * 사유가 생긴 상태라 잉크만 올린다 — 반려는 제재가 아니라 고쳐서 다시 낼 수 있는 상태여서 이용제한의 `destructive`
 * 틴트를 쓰지 않는다. 라벨은 스튜디오 목록의 소설 배지와 같은 낱말이다. */
function ViewBadge({ view }: { view: PublicationView }) {
  switch (view.kind) {
    case "public":
      return <span className={cn(BADGE_CLASS, "border-border text-foreground")}>공개 중</span>;
    case "withdrawn":
      return <span className={cn(BADGE_CLASS, "border-border text-muted-foreground")}>공개 거둠</span>;
    case "restricted":
      return <span className={cn(BADGE_CLASS, "border-transparent bg-destructive/10 text-destructive-text")}>이용제한</span>;
    case "inReview":
      return <span className={cn(BADGE_CLASS, "border-border text-muted-foreground")}>심사 대기</span>;
    case "reviewRejected":
      return <span className={cn(BADGE_CLASS, "border-border text-foreground")}>반려</span>;
    default:
      return null;
  }
}

function Lines({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-1 text-sm break-keep text-muted-foreground">{children}</div>;
}

function ViewBody({
  view,
  status,
  counts,
}: {
  view: PublicationView;
  status: NovelPublicationStatus;
  counts: { likeCount: number; viewCount: number } | undefined;
}) {
  const pricing = useCloverPricingQuery().data;
  const buyerPolicy = toBuyerPolicyCopy(pricing);
  const priceSentence = toPublishPriceSentence(
    pricing === undefined
      ? undefined
      : {
          freeChapterCount: pricing.novelFreeChapterCount,
          chapterPrice: pricing.novelReadCost,
          isPolicyV2Enabled: pricing.novelPublicPolicyV2Enabled === true,
        },
  );
  switch (view.kind) {
    case "noChapters":
      return (
        <Lines>
          <p>첫 화를 만든 뒤 노벨에 공개할 수 있어요.</p>
        </Lines>
      );
    case "unpublished":
      return (
        <Lines>
          <p>공개하면 로그인한 회원 누구나 노벨에서 읽을 수 있어요. {priceSentence}</p>
        </Lines>
      );
    case "blocked":
      return view.block === "permission" ? (
        <Lines>
          <p className="text-foreground">원작자가 이 작품으로 만든 소설의 공개를 허락하지 않았어요.</p>
          <p>원작자가 소설 허락을 ‘공개 소설까지’로 바꾸면 공개할 수 있어요. 나만 보는 소설로는 계속 읽고 고칠 수 있어요.</p>
        </Lines>
      ) : (
        <Lines>
          <p className="text-foreground">원작이 지금 공개돼 있지 않아 새로 공개할 수 없어요.</p>
        </Lines>
      );
    case "restricted":
      return (
        <Lines>
          <p className="text-foreground">{buyerPolicy.restrictedStatus}</p>
          <p>{CONTACT_LINE}</p>
        </Lines>
      );
    case "inReview":
      return (
        <Lines>
          <p className="text-foreground">
            운영자가 1화를 확인하고 있어요. 승인되면 노벨에 공개되고, 그다음 화부터는 바로 공개할 수 있어요.
          </p>
          <p>확인을 기다리는 동안에는 다른 화를 공개할 수 없어요.</p>
        </Lines>
      );
    case "reviewRejected":
      return (
        <Lines>
          <p className="text-foreground">운영자가 첫 공개를 반려했어요.</p>
          {view.reason !== "" && (
            // 운영자가 쓴 글 그대로라 길이·줄바꿈을 모른다. 윤곽 상자 하나로 남의 글임을 가른다.
            <div className="my-1 flex max-w-prose flex-col gap-1 rounded-lg border border-border p-3">
              <p className="text-xs font-medium text-muted-foreground">운영자가 남긴 사유</p>
              <p className="whitespace-pre-wrap text-foreground wrap-anywhere">{view.reason}</p>
            </div>
          )}
          <p>{toReapplyLine(view)}</p>
        </Lines>
      );
    case "withdrawn":
      // 판매 중단은 다시 열 수 없는 까닭이 원작이 아니라 운영 조치라 그 사실을 먼저 말한다.
      if (view.salesStopped) return <SalesStoppedLines status={buyerPolicy.salesStoppedStatus} />;
      return (
        <Lines>
          <p className="text-foreground">{buyerPolicy.withdrawnStatus}</p>
          <p>
            {view.canReopen
              ? buyerPolicy.withdrawnReopen
              : "원작이 지금 공개돼 있지 않아 다시 공개할 수 없어요."}
          </p>
        </Lines>
      );
    case "public": {
      const summary = [
        `${view.publishedCount === 1 ? "1화" : `1~${view.publishedCount}화`} 공개`,
        counts === undefined ? undefined : `좋아요 ${formatCompactCount(counts.likeCount)}`,
        counts === undefined ? undefined : `조회 ${formatCompactCount(counts.viewCount)}`,
      ]
        .filter((part) => part !== undefined)
        .join(" · ");
      return (
        <Lines>
          <p className="text-foreground tabular-nums">{summary}</p>
          {view.salesStopped && <p className="text-foreground">{buyerPolicy.salesStoppedStatus}</p>}
          {toPublicPendingLines(view, { republishBlock: status.republishBlock }).map((line) => (
            <p key={line}>{line}</p>
          ))}
          {view.salesStopped && <p>{CONTACT_LINE}</p>}
        </Lines>
      );
    }
  }
}

const CONTACT_LINE = "조치에 대해 묻고 싶은 것이 있으면 고객센터로 문의해 주세요.";

function SalesStoppedLines({ status }: { status: string }) {
  return (
    <Lines>
      <p className="text-foreground">{status}</p>
      <p>판매가 멈춘 동안은 다시 공개할 수 없어요. {CONTACT_LINE}</p>
    </Lines>
  );
}

function toReapplyLine(view: Extract<PublicationView, { kind: "reviewRejected" }>): string {
  if (view.canReapply) return "고친 뒤 다시 신청할 수 있어요.";
  if (view.block === "permission") return "원작자가 이 작품으로 만든 소설의 공개를 허락하지 않아 다시 신청할 수 없어요.";
  if (view.block === "source") return "원작이 지금 공개돼 있지 않아 다시 신청할 수 없어요.";
  return "첫 화를 만든 뒤 다시 신청할 수 있어요.";
}

function ViewActions({
  view,
  novelId,
  rejectionFixOrdinal,
  fixChapterId,
  firstChapterId,
  canRetry,
  onPublish,
  onRetry,
  onWithdraw,
}: {
  view: PublicationView;
  novelId: string;
  rejectionFixOrdinal: number | undefined;
  fixChapterId: string | undefined;
  firstChapterId: string | undefined;
  canRetry: boolean;
  onPublish: () => void;
  onRetry: () => void;
  onWithdraw: () => void;
}) {
  const buttons: ReactNode[] = [];
  if (canRetry) {
    buttons.push(
      <Button key="retry" type="button" variant="outline" size="sm" onClick={onRetry}>
        다시 시도
      </Button>,
    );
  }
  if (rejectionFixOrdinal !== undefined && fixChapterId !== undefined) {
    buttons.push(
      <Button key="fix" asChild variant="outline" size="sm">
        <Link to="/novels/$novelId/board" params={{ novelId }} search={{ select: `episode:${fixChapterId}` }}>
          {rejectionFixOrdinal}화 고치러 가기
        </Link>
      </Button>,
    );
  }
  switch (view.kind) {
    case "unpublished":
      buttons.push(
        <Button key="publish" type="button" variant="outline" size="sm" onClick={onPublish}>
          <Globe aria-hidden />
          노벨에 공개하기
        </Button>,
      );
      break;
    case "withdrawn":
      if (view.salesStopped) buttons.push(<InquiryButton key="inquiry" />);
      if (view.canReopen) {
        buttons.push(
          <Button key="publish" type="button" variant="outline" size="sm" onClick={onPublish}>
            <Globe aria-hidden />
            다시 공개하기
          </Button>,
        );
      }
      break;
    case "public":
      if (view.canRepublish) {
        buttons.push(
          <Button key="publish" type="button" variant="outline" size="sm" onClick={onPublish}>
            <Globe aria-hidden />
            다시 공개하기
          </Button>,
        );
      }
      // 판매가 멈춘 노벨은 게시자에게도 노벨 화면이 열리지 않는다(소장자만 읽는다) — 닿지 않는 길을 내지 않는다.
      if (!view.salesStopped) {
        buttons.push(
          <Button key="open" asChild variant="outline" size="sm">
            <Link to="/webnovels/$novelId" params={{ novelId }}>
              노벨에서 보기
            </Link>
          </Button>,
        );
      }
      if (view.salesStopped) buttons.push(<InquiryButton key="inquiry" />);
      buttons.push(
        <Button key="withdraw" type="button" variant="ghost" size="sm" onClick={onWithdraw}>
          공개 거두기
        </Button>,
      );
      break;
    case "inReview":
      buttons.push(
        <Button key="withdraw" type="button" variant="ghost" size="sm" onClick={onWithdraw}>
          신청 취소
        </Button>,
      );
      break;
    case "reviewRejected":
      // 반려 사유는 어느 화인지 말하지 않는다 — 신청한 1화로 보낸다. 심사 거절이 이미 고칠 화를 걸었으면 그것을 따른다.
      if (rejectionFixOrdinal === undefined && firstChapterId !== undefined) {
        buttons.push(
          <Button key="fix" asChild variant="outline" size="sm">
            <Link to="/novels/$novelId/board" params={{ novelId }} search={{ select: `episode:${firstChapterId}` }}>
              1화 고치러 가기
            </Link>
          </Button>,
        );
      }
      if (view.canReapply) {
        buttons.push(
          <Button key="publish" type="button" variant="outline" size="sm" onClick={onPublish}>
            <Globe aria-hidden />
            다시 신청하기
          </Button>,
        );
      }
      break;
    case "restricted":
      buttons.push(<InquiryButton key="inquiry" />);
      break;
    case "noChapters":
    case "blocked":
      break;
  }
  if (buttons.length === 0) return null;
  return <div className="flex flex-wrap gap-2">{buttons}</div>;
}

function InquiryButton() {
  return (
    <Button asChild variant="outline" size="sm">
      <Link to="/inquiries/new">문의하기</Link>
    </Button>
  );
}

/** "화별 가격" 펼침 목록 — 노벨 정책 스위치가 켜졌고 앞 화 다음 화를 공개한 적이 있을 때만. 접힌 머리에 유료 화 수를
 * 말해 펼치지 않아도 무엇이 들었는지 안다. 전환은 확인 모달을 거친다(되돌릴 수 없다). */
function ChapterPriceList({ novelId, status }: { novelId: string; status: NovelPublicationStatus }) {
  const pricing = useCloverPricingQuery().data;
  if (pricing?.novelPublicPolicyV2Enabled !== true) return null;
  const rows = toPublishedPriceRows(status.publishedChapters, pricing.novelFreeChapterCount);
  if (rows.length === 0) return null;
  const paidCount = rows.filter((row) => row.price > 0).length;

  return (
    <details className="group w-full max-w-prose">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 rounded-md text-sm font-medium text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring focus-visible:outline-solid [&::-webkit-details-marker]:hidden">
        화별 가격
        <span className="font-normal text-muted-foreground tabular-nums">
          · {paidCount > 0 ? `유료 ${paidCount}화` : "모두 무료"}
        </span>
        <ChevronDown aria-hidden className="size-4 text-muted-foreground motion-safe:transition-transform group-open:rotate-180" />
      </summary>
      <ul className="mt-2 flex flex-col">
        {rows.map((row) => (
          <li
            key={row.chapterId}
            className="flex min-h-10 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border py-1 text-sm last:border-b-0"
          >
            <span className="text-foreground tabular-nums">
              {row.ordinal}화
              <span className="text-muted-foreground">
                {" "}
                · {row.price === 0 ? "무료" : `유료 · 클로버 ${row.price.toLocaleString()}개`}
              </span>
            </span>
            {row.price > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => void MakeChapterFreeModal.call({ novelId, chapterId: row.chapterId, ordinal: row.ordinal })}
              >
                무료로 전환
              </Button>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs break-keep text-muted-foreground">
        무료로 바꾼 화는 다시 유료로 되돌릴 수 없어요. 이미 산 회원에게 클로버를 돌려드리지 않아요.
      </p>
    </details>
  );
}
