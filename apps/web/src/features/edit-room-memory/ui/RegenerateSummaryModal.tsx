import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Loader2, TriangleAlert } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys, useChatRoomMemoryQuery } from "@/entities/chat-room";
import {
  CloverIcon,
  CloverSpendSummary,
  isCloverInsufficient,
  useCloverBalanceQuery,
  useCloverPricingQuery,
} from "@/entities/clover";
import { createSingleFlight } from "@/shared/lib/async/singleFlight";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useRegenerateMemorySummaryMutation } from "../api/memoryMutations";
import { toRegenerateSummaryFailure } from "../model/regenerateSummaryFailure";

type RegenerateSummaryModalProps = {
  roomId: string;
};

/** 요약을 AI 로 다시 만들기 전에 가격·잔액을 보이고 동의를 받아 바로 만든다. 다시 만들었으면 `true`.
 *
 * 버전·요약 출처·가격은 열 때 받아 두지 않고 캐시에서 읽는다 — 그사이 요약이 바뀌었다는 거절(버전 충돌)을 받으면 기억을
 * 다시 받기만 해도 이 대화가 바뀐 요약의 버전과 출처로 다시 묻게 된다. 확인한 가격이 지금 가격과 달라 거절되면 서버가 알려 준
 * 새 가격으로 바꿔 다시 묻는다.
 *
 * 잔액이 모자라면(화면의 잔액이 그렇거나 서버가 잔액 부족으로 거절하면) 실행 버튼이 "클로버 채우기"로 바뀐다 — 노벨 화
 * 소장과 같은 모양이다. 요청 중에는 실행 버튼을 `aria-disabled` 로 막는다(`disabled` 는 포커스를 빼앗는다). 버튼 순서는
 * `취소` 먼저(푸터 프리미티브가 강제). 이 화면의 유일한 솔리드 채움은 실행 버튼이다. */
export const RegenerateSummaryModal = createCallable<RegenerateSummaryModalProps, boolean>(({ call, roomId }) => {
  const queryClient = useQueryClient();
  const memoryQuery = useChatRoomMemoryQuery(roomId);
  const pricingQuery = useCloverPricingQuery();
  const { data: clover } = useCloverBalanceQuery();
  const regenerate = useRegenerateMemorySummaryMutation(roomId);
  const [quotedCost, setQuotedCost] = useState<number | undefined>(undefined);
  const [isServerShort, setIsServerShort] = useState(false);
  const [notice, setNotice] = useState<string | undefined>(undefined);
  const [isClosedByServer, setIsClosedByServer] = useState(false);
  // 같은 순간 두 번 누르면 `isPending`이 다시 그려지기 전에 두 번째가 들어와 요청이 둘 나간다 — 렌더를 기다리지 않고 막는다.
  const [runExclusive] = useState(createSingleFlight);

  const memory = memoryQuery.data;
  const summary = memory?.summary;
  const cost = quotedCost ?? pricingQuery.data?.memorySummaryRegenerateCost;
  const balance = clover?.balance;
  const isInsufficient =
    isServerShort || (balance !== undefined && cost !== undefined && isCloverInsufficient(balance, cost));
  const isConfirmBlocked = regenerate.isPending || cost === undefined || summary === undefined || isClosedByServer;

  async function handleConfirm() {
    await runExclusive(confirm);
  }

  async function confirm() {
    if (regenerate.isPending || cost === undefined || memory === undefined || summary === undefined || isClosedByServer) {
      return;
    }
    setNotice(undefined);
    try {
      await regenerate.mutateAsync({ version: memory.version, expectedCost: cost });
      call.end(true);
    } catch (error) {
      const failure = toRegenerateSummaryFailure(error);
      switch (failure.kind) {
        case "cloverRequired":
          setIsServerShort(true);
          return;
        case "priceChanged":
          if (failure.currentCost === undefined) {
            setQuotedCost(undefined);
            await pricingQuery.refetch();
          } else {
            setQuotedCost(failure.currentCost);
          }
          setNotice(failure.message);
          return;
        case "stale": {
          // 요약이 사라졌으면 "아직 다시 만들 요약이 없어요" 한 줄만 남긴다 — 바뀐 요약을 확인하라는 문장은 그때 틀린 말이다.
          const refetched = await memoryQuery.refetch();
          if (refetched.data?.summary !== undefined) setNotice(failure.message);
          return;
        }
        case "disabled":
          // 기억 응답을 다시 받으면 기능 칸이 꺼져 패널에서 다시 만들기 버튼이 사라진다.
          void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
          setIsClosedByServer(true);
          setNotice(failure.message);
          return;
        case "inProgress":
        case "unavailable":
        case "message":
          setNotice(failure.message);
          return;
      }
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="break-keep">요약을 다시 만들까요?</DialogTitle>
          <DialogDescription>
            바로 앞 요약과 이 요약에 정리된 대화로 요약을 새로 써요. 다시 만들기 전 글은 &lsquo;되돌리기&rsquo;로 한 번 되돌릴
            수 있어요.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {summary?.source === "user" && (
            <p className="flex gap-2 rounded-lg border border-border px-3.5 py-2.5 text-xs break-keep text-foreground">
              <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0 text-muted-foreground" />
              직접 고친 요약이에요. 다시 만들면 고친 내용이 새 요약으로 바뀌어요.
            </p>
          )}
          {memory !== undefined && summary === undefined && (
            <p className="text-sm break-keep text-foreground">아직 다시 만들 요약이 없어요.</p>
          )}
          {cost === undefined ? (
            <p className="text-sm break-keep text-muted-foreground">
              {pricingQuery.isError ? "가격을 불러오지 못했어요. 잠시 후 다시 시도해 주세요." : "가격을 확인하는 중이에요."}
            </p>
          ) : (
            <CloverSpendSummary cost={cost} balance={balance} />
          )}
          {isServerShort && (balance === undefined || cost === undefined || !isCloverInsufficient(balance, cost)) && (
            // 화면의 잔액이 낡아 금액 줄이 모자람을 말하지 않을 때만 — 잔액을 다시 받으면 금액 줄이 같은 말을 한다.
            <p className="text-sm break-keep text-foreground">클로버가 모자라요. 클로버를 채운 뒤 다시 해 주세요.</p>
          )}
          <p className="text-xs break-keep text-muted-foreground">만들지 못하면 쓴 클로버를 돌려드려요.</p>
          {notice !== undefined && (
            <p role="alert" className="text-sm break-keep text-destructive-text">
              {notice}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(false)}>
            취소
          </Button>
          {isInsufficient ? (
            <Button asChild>
              <Link to="/clover" onClick={() => call.end(false)}>
                <CloverIcon className="size-4" />
                클로버 채우기
              </Link>
            </Button>
          ) : (
            <Button
              type="button"
              aria-disabled={isConfirmBlocked}
              className="aria-disabled:opacity-65"
              onClick={() => void handleConfirm()}
            >
              {/* 요약 호출은 수십 초 걸릴 수 있다. 진행 표시라 줄인 모션에서도 돈다. */}
              {regenerate.isPending && <Loader2 aria-hidden className="size-4 animate-spin" />}
              {regenerate.isPending ? "만드는 중…" : "다시 만들기"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
