import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { Heart } from "lucide-react";
import { useState } from "react";
import { useDebounce } from "react-use";
import { toast } from "sonner";

import { webnovelKeys, type WebnovelDetailResponse } from "@/entities/webnovel";
import { formatCompactCount } from "@/shared/lib/number/formatCompactCount";

import { useToggleWebnovelLikeMutation } from "../api/useToggleWebnovelLikeMutation";
import { applyWebnovelLike } from "../model/applyWebnovelLike";

/** 연타를 묶어 마지막 뜻만 보내는 시간. 작품 상세의 좋아요와 같은 값이다. */
const LIKE_SYNC_DEBOUNCE_MS = 400;

type WebnovelLikeButtonProps = {
  novelId: string;
  /** 서버가 준 지금 값(작품 정보 응답). */
  liked: boolean;
  likeCount: number;
  /** 판형 안이면 크기를 px 로 고정한 클래스를 받는다(판형 안 글자가 브라우저 기본 글자 크기를 따르면 쪽 수가 바뀐다). */
  className?: string;
  iconClassName?: string;
};

/** 노벨 좋아요 — 작품 정보의 행동 줄과 화 끝 쪽에 같은 것이 놓인다(좋아요는 소설 단위다). 누르는 즉시 화면에 반영하고
 * 네트워크만 묶어 보낸다: 성공하면 작품 정보 캐시에 그 값을 먼저 쓰고 낙관값을 풀어 버튼이 깜빡이지 않게 한 뒤 서버
 * 값을 다시 받는다. 실패하면 낙관값만 풀어 마지막 서버 값으로 돌아간다. 요청 중에는 보내지 않고, 끝난 뒤 바뀐 뜻이
 * 남아 있으면 그때 보낸다(작품 상세 좋아요와 같은 정산 순서).
 *
 * 눌린 상태는 강조색 글자와 채운 하트다. ghost hover 는 `secondary` 다 — 이 버튼이 놓이는 표면 어디서나 보인다. */
export function WebnovelLikeButton({ novelId, liked, likeCount, className, iconClassName }: WebnovelLikeButtonProps) {
  const queryClient = useQueryClient();
  const toggle = useToggleWebnovelLikeMutation(novelId);
  const [desired, setDesired] = useState<boolean | undefined>(undefined);

  useDebounce(
    () => {
      if (desired === undefined || desired === liked || toggle.isPending) return;
      const next = desired;
      const release = () => setDesired((current) => (current === next ? undefined : current));
      void toggle.mutateAsync(next).then(
        () => {
          queryClient.setQueryData<WebnovelDetailResponse>(webnovelKeys.detail(novelId), (old) => applyWebnovelLike(old, next));
          release();
          void queryClient.invalidateQueries({ queryKey: webnovelKeys.detail(novelId) });
        },
        () => {
          toast.error("좋아요 처리에 실패했어요. 잠시 후 다시 시도해주세요.");
          release();
          void queryClient.invalidateQueries({ queryKey: webnovelKeys.detail(novelId) });
        },
      );
    },
    LIKE_SYNC_DEBOUNCE_MS,
    [desired, liked, toggle.isPending],
  );

  const isLiked = desired ?? liked;
  // 낙관값이 서버 값과 다를 때만 수를 하나 옮긴다.
  let delta = 0;
  if (isLiked !== liked) delta = isLiked ? 1 : -1;
  const count = Math.max(likeCount + delta, 0);

  return (
    <Button
      type="button"
      variant="ghost"
      aria-pressed={isLiked}
      onClick={() => setDesired((current) => !(current ?? liked))}
      // 눌린 색은 호출부 글자색보다 뒤에 둬야 이긴다.
      className={cn("gap-1.5 tabular-nums hover:bg-secondary", className, isLiked && "text-primary hover:text-primary")}
    >
      <Heart aria-hidden className={cn("size-4", isLiked && "fill-primary", iconClassName)} />
      <span aria-hidden>{formatCompactCount(count)}</span>
      {/* 눌림은 `aria-pressed` 가 말하므로 이름은 늘 같다. */}
      <span className="sr-only">좋아요 {count.toLocaleString()}개</span>
    </Button>
  );
}
