import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { Globe, Loader2 } from "lucide-react";
import { useId, type ReactNode } from "react";
import { toast } from "sonner";

import { useCloverPricingQuery } from "@/entities/clover";
import type { NovelPublicationStatus } from "@/entities/novel";
import { useWebnovelQuery } from "@/entities/webnovel";
import { formatCompactCount } from "@/shared/lib/number/formatCompactCount";

import { toPublishFailureMessage } from "../model/publishFailure";
import {
  toPublicationView,
  toPublicPendingLines,
  toPublishPriceSentence,
  toRejectionNotice,
  type PublicationView,
} from "../model/publicationView";
import { useNovelPublishActions } from "../model/useNovelPublishActions";
import { PublishNovelModal } from "./PublishNovelModal";
import { WithdrawNovelPublicationModal } from "./WithdrawNovelPublicationModal";

type PublishableNovel = { id: string; chapters: readonly { id: string; ordinal: number }[] };

const BADGE_CLASS = "inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-badge font-medium";

/** 작품 정보(`/novels/$novelId`)의 "노벨 공개" 절 — 행동 줄 아래, 소개 위. 공개 상태(공개 전·공개 중·거둠·운영 조치·
 * 원작 때문에 막힘)와 요청 중("확인 중 · n/N")·요청 실패(심사 장애·상한·낡음), 마지막 심사 거절을 한자리에서 말한다.
 *
 * 카드 껍데기 없이 위 경계선과 제목으로만 갈린다. 이 절의 버튼은 전부 outline·ghost 다 — 이 화면의 솔리드 채움은
 * "이어 읽기" 하나로 남는다. 공개 상태를 못 읽으면(소설화를 쓸 수 없는 계정, 노벨이 꺼져 있음, 일시 실패) 절을 그리지
 * 않는다 — 공개는 이 화면의 주된 일이 아니다. 공개·거두기 모달은 여기 마운트한다. */
export function NovelPublicSection({ novel }: { novel: PublishableNovel }) {
  const headingId = useId();
  const actions = useNovelPublishActions(novel);
  const status = actions.publication.data;
  const view = status === undefined ? undefined : toPublicationView(status);
  // 좋아요·조회 수는 노벨 작품 정보에만 있다 — 공개 중일 때만 묻는다.
  const counts = useWebnovelQuery(novel.id, { enabled: view?.kind === "public" }).data;

  if (status === undefined || view === undefined) return null;

  const runState = actions.runState;
  const isChecking = runState.kind === "checking";
  const failureMessage = runState.kind === "failed" ? toPublishFailureMessage(runState.failure) : undefined;
  const rejection =
    !isChecking && status.lastScreening?.outcome === "rejected" ? toRejectionNotice(status.lastScreening) : undefined;

  async function publish() {
    if (status === undefined || isChecking) return;
    actions.clearFailure();
    if (await actions.openPublish(status)) toast.success("노벨에 공개했어요.");
  }

  async function retry() {
    if (isChecking) return;
    if (await actions.retry()) toast.success("노벨에 공개했어요.");
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col items-start gap-3 border-t border-border pt-6">
      <PublishNovelModal />
      <WithdrawNovelPublicationModal />
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={headingId} className="text-lg font-semibold text-foreground">
          노벨 공개
        </h2>
        <ViewBadge view={view} />
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
          canRetry={runState.kind === "failed" && (runState.failure.kind === "unavailable" || runState.failure.kind === "failed")}
          onPublish={() => void publish()}
          onRetry={() => void retry()}
          onWithdraw={() => void actions.openWithdraw()}
        />
      )}
    </section>
  );
}

function ViewBadge({ view }: { view: PublicationView }) {
  switch (view.kind) {
    case "public":
      return <span className={cn(BADGE_CLASS, "border-border text-foreground")}>공개 중</span>;
    case "withdrawn":
      return <span className={cn(BADGE_CLASS, "border-border text-muted-foreground")}>공개 거둠</span>;
    case "restricted":
      return <span className={cn(BADGE_CLASS, "border-transparent bg-destructive/10 text-destructive-text")}>이용제한</span>;
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
  const priceSentence = toPublishPriceSentence(
    pricing === undefined ? undefined : { freeChapterCount: pricing.novelFreeChapterCount, chapterPrice: pricing.novelReadCost },
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
          <p className="text-foreground">운영 정책에 따라 노벨에서 내려졌어요. 소장한 회원도 지금은 볼 수 없어요.</p>
          <p>조치에 대해 묻고 싶은 것이 있으면 고객센터로 문의해 주세요.</p>
        </Lines>
      );
    case "withdrawn":
      return (
        <Lines>
          <p className="text-foreground">공개를 거둔 소설이에요. 노벨에 보이지 않고, 소장한 회원도 지금은 볼 수 없어요.</p>
          <p>
            {view.canReopen
              ? "다시 공개하면 소장한 화도 다시 열려요."
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
          {toPublicPendingLines(view, { republishBlocked: status.republishBlock !== null }).map((line) => (
            <p key={line}>{line}</p>
          ))}
        </Lines>
      );
    }
  }
}

function ViewActions({
  view,
  novelId,
  rejectionFixOrdinal,
  fixChapterId,
  canRetry,
  onPublish,
  onRetry,
  onWithdraw,
}: {
  view: PublicationView;
  novelId: string;
  rejectionFixOrdinal: number | undefined;
  fixChapterId: string | undefined;
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
      buttons.push(
        <Button key="open" asChild variant="outline" size="sm">
          <Link to="/webnovels/$novelId" params={{ novelId }}>
            노벨에서 보기
          </Link>
        </Button>,
        <Button key="withdraw" type="button" variant="ghost" size="sm" onClick={onWithdraw}>
          공개 거두기
        </Button>,
      );
      break;
    case "restricted":
      buttons.push(
        <Button key="inquiry" asChild variant="outline" size="sm">
          <Link to="/inquiries/new">문의하기</Link>
        </Button>,
      );
      break;
    case "noChapters":
    case "blocked":
      break;
  }
  if (buttons.length === 0) return null;
  return <div className="flex flex-wrap gap-2">{buttons}</div>;
}
