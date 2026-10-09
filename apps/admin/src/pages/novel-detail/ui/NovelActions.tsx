import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { useId, useState } from "react";

import {
  useHomeNovelCurationsQuery,
  type AdminHomeNovelCurationSlot,
  type AdminNovelDetailResponse,
} from "@/entities/admin-novel";

import { HomeNovelCurationConfirmModal } from "./HomeNovelCurationConfirmModal";
import { NovelModerationConfirmModal } from "./NovelModerationConfirmModal";

type NovelActionsProps = {
  novel: AdminNovelDetailResponse;
  onSuccess: () => void;
};

/** 조치 열·시트 하나에 홈 노벨과 상태 조치를 두 묶음으로 둔다(작품 상세와 같은 짜임) — 둘 다 이 노벨을 운영자가 바꾸는
 * 일이라 한 자리에서 찾고, 묶음 제목으로 어느 쪽 버튼인지 가른다. */
export function NovelActions({ novel, onSuccess }: NovelActionsProps) {
  const curationHeadingId = useId();
  const moderationHeadingId = useId();
  const novelTitle = novel.title || "(제목 없음)";
  const isRestricted = novel.moderationStatus === "restricted";

  return (
    <div className="flex flex-col gap-4">
      <section aria-labelledby={curationHeadingId} className="flex flex-col gap-2">
        <h3 id={curationHeadingId} className="text-sm font-semibold text-foreground">
          홈 노벨
        </h3>
        <HomeNovelCurationActions novel={novel} novelTitle={novelTitle} onSuccess={onSuccess} />
      </section>

      <section aria-labelledby={moderationHeadingId} className="flex flex-col gap-2 border-t border-border pt-4">
        <h3 id={moderationHeadingId} className="text-sm font-semibold text-foreground">
          상태 조치
        </h3>
        <p className="break-keep text-sm text-muted-foreground">
          {isRestricted ? "이용제한 중이에요. 독자에게 보이지 않아요." : "이용제한하면 독자 목록·열람에서 바로 빠져요."}
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
