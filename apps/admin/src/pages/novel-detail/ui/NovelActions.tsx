import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { useNavigate } from "@tanstack/react-router";
import { useId, useState } from "react";

import {
  useHomeNovelCurationsQuery,
  type AdminHomeNovelCurationSlot,
  type AdminNovelDetailResponse,
} from "@/entities/admin-novel";
import { useSessionQuery } from "@/entities/session";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useRememberedListSearch } from "@/shared/lib/list-search-memory/listSearchMemory";

import { HomeNovelCurationConfirmModal } from "./HomeNovelCurationConfirmModal";
import { NovelModerationConfirmModal } from "./NovelModerationConfirmModal";
import { NovelReviewConfirmModal } from "./NovelReviewConfirmModal";
import { NovelSalesConfirmModal } from "./NovelSalesConfirmModal";

type NovelActionsProps = {
  novel: AdminNovelDetailResponse;
  onSuccess: () => void;
};

/** 조치 열·시트 하나에 홈 노벨과 상태 조치를 두 묶음으로 둔다(작품 상세와 같은 짜임) — 둘 다 이 노벨을 운영자가 바꾸는
 * 일이라 한 자리에서 찾고, 묶음 제목으로 어느 쪽 버튼인지 가른다. 첫 공개 승인 대기면 운영자가 지금 할 일이라 "첫 공개
 * 심사" 묶음을 맨 위에 더한다. 대기 중에도 이용제한은 걸 수 있어 나머지 두 묶음은 그대로 둔다.
 *
 * 상태 조치는 정책 스위치(`/admin/me` 의 `novelPublicPolicyV2Enabled`)가 켜져 있으면 판매 중단을 이용제한보다 위에 둔다 —
 * 산 회원의 열람을 남기는 가벼운 조치를 먼저 보게 하고, 열람을 끊고 환급하는 이용제한은 불가피할 때 고르게 한다. 꺼져
 * 있으면 판매 중단이 없던 때와 같은 화면이다(멈춘 채 스위치가 꺼진 노벨만 상태와 막힌 재개 버튼을 보인다). */
export function NovelActions({ novel, onSuccess }: NovelActionsProps) {
  const reviewHeadingId = useId();
  const curationHeadingId = useId();
  const moderationHeadingId = useId();
  const novelTitle = novel.title || "(제목 없음)";
  const isRestricted = novel.moderationStatus === "restricted";
  const isPendingReview = novel.reviewStatus === "pending";
  const isPolicyOn = useSessionQuery().data?.novelPublicPolicyV2Enabled === true;
  const navigate = useNavigate();
  const rememberedListSearch = useRememberedListSearch("/novels/");
  const goToList = () => void navigate({ to: "/novels", search: rememberedListSearch ?? {} });

  return (
    <div className="flex flex-col gap-4">
      {isPendingReview && (
        <section aria-labelledby={reviewHeadingId} className="flex flex-col gap-2">
          <h3 id={reviewHeadingId} className="text-sm font-semibold text-foreground">
            첫 공개 심사
          </h3>
          <p className="break-keep text-sm text-muted-foreground">1화를 읽고 승인하면 독자에게 열려요.</p>
          {/* 승인이 이 조치 열의 유일한 채움 버튼이다 — 대기 노벨에서 운영자가 내릴 주된 결정이라서. */}
          <Button
            type="button"
            onClick={() =>
              void NovelReviewConfirmModal.call({ novelId: novel.id, novelTitle, action: "approve", onSuccess, onNovelGone: goToList })
            }
          >
            승인
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              void NovelReviewConfirmModal.call({ novelId: novel.id, novelTitle, action: "reject", onSuccess, onNovelGone: goToList })
            }
          >
            반려
          </Button>
        </section>
      )}

      <section
        aria-labelledby={curationHeadingId}
        className={isPendingReview ? "flex flex-col gap-2 border-t border-border pt-4" : "flex flex-col gap-2"}
      >
        <h3 id={curationHeadingId} className="text-sm font-semibold text-foreground">
          홈 노벨
        </h3>
        <HomeNovelCurationActions novel={novel} novelTitle={novelTitle} onSuccess={onSuccess} />
      </section>

      <section aria-labelledby={moderationHeadingId} className="flex flex-col gap-2 border-t border-border pt-4">
        <h3 id={moderationHeadingId} className="text-sm font-semibold text-foreground">
          상태 조치
        </h3>
        {(isPolicyOn || novel.salesStoppedAt !== null) && (
          <NovelSalesActions novel={novel} novelTitle={novelTitle} isPolicyOn={isPolicyOn} onSuccess={onSuccess} />
        )}
        <p className="break-keep text-sm text-muted-foreground">
          {restrictionDescription(isRestricted, isPolicyOn)}
        </p>
        <Button
          type="button"
          variant="outline"
          onClick={() =>
            void NovelModerationConfirmModal.call({
              novelId: novel.id,
              novelTitle,
              action: isRestricted ? "lift" : "restrict",
              onSuccess,
            })
          }
        >
          {isRestricted ? "이용제한 해제" : "이용제한"}
        </Button>
      </section>
    </div>
  );
}

/** 이용제한 설명. 스위치가 켜져 있으면 판매 중단이 위에 있어, 이용제한은 열람까지 막아야 할 때 쓰는 것임을 말한다. */
function restrictionDescription(isRestricted: boolean, isPolicyOn: boolean): string {
  if (isRestricted) return "이용제한 중이에요. 독자에게 보이지 않아요.";
  if (isPolicyOn) {
    return "이용제한은 열람까지 막아야 할 때만 써요. 독자 목록·열람에서 바로 빠지고, 산 회원에게 클로버를 돌려드려요.";
  }
  return "이용제한하면 독자 목록·열람에서 바로 빠져요.";
}

type NovelSalesActionsProps = {
  novel: AdminNovelDetailResponse;
  novelTitle: string;
  isPolicyOn: boolean;
  onSuccess: () => void;
};

/** 판매 중단·재개. 이용제한과 따로 걸리고 따로 풀려, 이용제한 중이어도 판매 중단 상태를 따로 보인다. 서버는 스위치가 꺼져
 * 있으면 재개도 거부하므로(끄기 전에 재개하는 것이 순서다) 꺼짐에서는 재개 버튼을 막고 이유를 버튼 바로 아래에 적는다. */
function NovelSalesActions({ novel, novelTitle, isPolicyOn, onSuccess }: NovelSalesActionsProps) {
  const disabledReasonId = useId();
  const isStopped = novel.salesStoppedAt !== null;
  const action = isStopped ? "resume" : "stop";

  return (
    <div className="flex flex-col gap-2 border-b border-border pb-3">
      <p className="break-keep text-sm text-muted-foreground">
        {novel.salesStoppedAt !== null
          ? `${formatDateTime(novel.salesStoppedAt)}부터 판매 중단 중이에요. 목록·홈에 보이지 않고 새로 팔지 않아요. 산 회원은 계속 읽어요.`
          : "판매를 멈추면 목록·홈에서 빠지고 새로 팔지 않아요. 산 회원은 계속 읽고 환급은 없어요. 게시자는 새 화·다시 공개를 낼 수 없어요."}
      </p>
      <Button
        type="button"
        variant="outline"
        disabled={!isPolicyOn}
        aria-describedby={isPolicyOn ? undefined : disabledReasonId}
        onClick={() => void NovelSalesConfirmModal.call({ novelId: novel.id, novelTitle, action, onSuccess })}
      >
        {isStopped ? "판매 재개" : "판매 중단"}
      </Button>
      {!isPolicyOn && (
        <p id={disabledReasonId} className="break-keep text-xs text-muted-foreground">
          정책 스위치가 꺼져 있어 재개할 수 없어요. 스위치를 다시 켜야 재개할 수 있어요.
        </p>
      )}
    </div>
  );
}

type HomeNovelCurationActionsProps = {
  novel: AdminNovelDetailResponse;
  novelTitle: string;
  onSuccess: () => void;
};

/** 이 노벨을 홈 노벨 한 자리에 걸거나, 다른 자리로 옮기거나, 걸린 자리를 비운다. 독자에게 안 보이는 노벨은 서버가 400 으로
 * 거부하므로 거는 버튼을 미리 막고 이유를 보인다 — 판정은 상세의 `readable` 과 같은 것이다. 놓이는 곳이 늘 `card`·`popover`
 * 표면이라 스켈레톤은 `secondary` 다(`muted` 는 같은 값이라 보이지 않는다). */
function HomeNovelCurationActions({ novel, novelTitle, onSuccess }: HomeNovelCurationActionsProps) {
  const homeNovelCurationsQuery = useHomeNovelCurationsQuery();

  if (homeNovelCurationsQuery.isPending) {
    return <div className="h-24 animate-pulse rounded-lg bg-secondary" />;
  }
  if (homeNovelCurationsQuery.isError) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p role="alert" className="text-sm text-destructive-text">
          홈 노벨 현황을 불러오지 못했어요.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={() => void homeNovelCurationsQuery.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  const slots = homeNovelCurationsQuery.data;
  const currentSlot = slots.find((slot) => slot.novel?.id === novel.id) ?? null;

  return (
    <div className="flex flex-col gap-3">
      {currentSlot === null ? (
        <p className="text-sm text-muted-foreground">홈 노벨에 걸려 있지 않아요.</p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="break-keep text-sm text-foreground">
            홈 노벨 <span className="font-semibold tabular-nums">{currentSlot.position}번</span> 자리에 걸려 있어요.
          </p>
          {!currentSlot.isListed && (
            <p className="break-keep text-sm text-muted-foreground">
              지금은 독자에게 보이지 않아 홈에서 빠져 있어요. 다시 보이게 되면 그 자리에 돌아와요.
            </p>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              void HomeNovelCurationConfirmModal.call({ mode: "clear", position: currentSlot.position, novelTitle, onSuccess })
            }
          >
            {currentSlot.position}번 자리 비우기
          </Button>
        </div>
      )}

      {novel.readable ? (
        <PositionPicker
          // 현황이 바뀌면(다른 운영자의 지정 등) 고른 자리를 처음 값으로 되돌린다.
          key={slots.map((slot) => slot.novel?.id ?? "-").join(",")}
          slots={slots}
          currentPosition={currentSlot?.position ?? null}
          onPick={(slot) =>
            void HomeNovelCurationConfirmModal.call({
              mode: "set",
              position: slot.position,
              novelId: novel.id,
              novelTitle,
              replacingTitle: slot.novel === null ? null : slot.novel.title || "(제목 없음)",
              fromPosition: currentSlot?.position ?? null,
              onSuccess,
            })
          }
        />
      ) : (
        <p className="break-keep text-sm text-muted-foreground">독자에게 보이지 않는 노벨은 홈에 걸 수 없어요.</p>
      )}
    </div>
  );
}

type PositionPickerProps = {
  slots: AdminHomeNovelCurationSlot[];
  currentPosition: number | null;
  onPick: (slot: AdminHomeNovelCurationSlot) => void;
};

/** 걸 자리 고르기. 처음 값은 첫 빈 자리(없으면 1번)이고, 이미 걸린 자리는 목록에서 뺀다 — 같은 자리에 다시 거는 일은 감사
 * 로그만 늘린다. 각 자리에 지금 걸린 노벨 제목을 보여 무엇을 밀어내는지 고르기 전에 안다. */
function PositionPicker({ slots, currentPosition, onPick }: PositionPickerProps) {
  const selectId = useId();
  const candidates = slots.filter((slot) => slot.position !== currentPosition);
  const [position, setPosition] = useState(
    () => (candidates.find((slot) => slot.novel === null) ?? candidates[0])?.position ?? null,
  );
  const picked = candidates.find((slot) => slot.position === position) ?? null;

  if (candidates.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={selectId}>{currentPosition === null ? "걸 자리" : "옮길 자리"}</Label>
      <Select value={position === null ? "" : String(position)} onValueChange={(value) => setPosition(Number(value))}>
        <SelectTrigger id={selectId} className="w-full">
          <SelectValue placeholder="자리를 고르세요" />
        </SelectTrigger>
        <SelectContent>
          {candidates.map((slot) => (
            <SelectItem key={slot.position} value={String(slot.position)}>
              <span className="tabular-nums">{slot.position}번</span>
              <span className="truncate text-muted-foreground">
                {slot.novel === null ? "비어 있음" : slot.novel.title || "(제목 없음)"}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button type="button" variant="outline" disabled={picked === null} onClick={() => picked && onPick(picked)}>
        {currentPosition === null ? "홈 노벨에 걸기" : "이 자리로 옮기기"}
      </Button>
    </div>
  );
}
