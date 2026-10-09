import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";

import { CloverBalance, CloverIcon, isCloverInsufficient, useCloverBalanceQuery } from "@/entities/clover";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { usePurchaseWebnovelChapterMutation } from "../api/usePurchaseWebnovelChapterMutation";
import { toPurchaseFailure } from "../model/purchaseFailure";

type PurchaseWebnovelChapterModalProps = {
  novelId: string;
  chapterId: string;
  ordinal: number;
  /** 설명 줄 — 소설 제목과 화 이름. */
  novelTitle: string;
  episodeLabel: string;
  /** 서버가 준 화당 가격. 요청의 `expectedPrice` 로도 같은 값을 싣는다. */
  price: number;
  /** 무료로 미리 볼 수 있는 앞 화 수(구매 전 고지의 마지막 문장). */
  freeChapterCount: number;
};

/** 노벨 화 하나를 소장하기 전에 금액과 구매 전 고지를 보이고 동의를 받아 바로 산다. 사고 나면 `true` — 같은 주소의
 * 화면이 본문을 다시 받아 연다(캐시 무효화는 뮤테이션이 한다).
 *
 * 금액 줄은 건마다 보인다: "클로버 30개를 써요 · 남은 클로버 240". 잔액이 모자라면 남은 클로버가 "부족해요"로 바뀌고
 * 모자란 수를 문장으로 말하며, 실행 버튼이 "클로버 채우기"(클로버 화면으로 가는 링크)로 바뀐다 — 이 화면에서 할 수
 * 있는 다음 일이 그것뿐이라서다. 화면의 잔액이 낡아 서버가 잔액 부족으로 거절해도 같은 모양으로 바꾼다.
 *
 * 구매 전 고지는 약관의 유료 열람 조항과 같은 내용이다 — 문장을 바꾸면 두 곳을 함께 바꾼다. 테두리 상자에 담고 첫
 * 문장만 본문 잉크로 둔다(무엇을 사는가). 고지가 길어 낮은 화면에서는 본문만 스크롤한다(`DialogBody`).
 *
 * 버튼 순서는 `취소` 먼저다(푸터 프리미티브가 강제). 요청 중에는 실행 버튼을 `aria-disabled` 로 막는다 — `disabled`
 * 는 포커스를 빼앗는다. 노벨 화면 위젯 안에 마운트한다(루트에 두면 노벨 코드가 첫 화면 번들로 끌려온다). */
export const PurchaseWebnovelChapterModal = createCallable<PurchaseWebnovelChapterModalProps, boolean>(
  ({ call, novelId, chapterId, ordinal, novelTitle, episodeLabel, price: initialPrice, freeChapterCount }) => {
    const { data: clover } = useCloverBalanceQuery();
    const purchase = usePurchaseWebnovelChapterMutation();
    const [price, setPrice] = useState(initialPrice);
    const [isServerShort, setIsServerShort] = useState(false);
    const [notice, setNotice] = useState<string | undefined>(undefined);
    const balance = clover?.balance;
    const isInsufficient = isServerShort || (balance !== undefined && isCloverInsufficient(balance, price));
    const shortage = balance === undefined ? undefined : Math.max(price - balance, 0);

    async function handleConfirm() {
      if (purchase.isPending) return;
      setNotice(undefined);
      try {
        await purchase.mutateAsync({ novelId, chapterId, expectedPrice: price });
        call.end(true);
      } catch (error) {
        const failure = toPurchaseFailure(error);
        switch (failure.kind) {
          case "insufficient":
            setIsServerShort(true);
            return;
          case "priceChanged":
            setPrice(failure.currentPrice);
            setNotice("그사이 가격이 바뀌었어요. 바뀐 금액을 확인하고 다시 소장해 주세요.");
            return;
          case "notForSale":
            // 무료 화이거나 내가 공개한 소설이라 이미 읽을 수 있다 — 화면이 다시 받아 본문을 연다.
            call.end(true);
            return;
          case "missing":
            toast.error("지금은 소장할 수 없는 화예요.");
            call.end(true);
            return;
          case "failed":
            setNotice("소장하지 못했어요. 잠시 후 다시 시도해 주세요.");
            return;
        }
      }
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="break-keep">{ordinal}화를 소장할까요?</DialogTitle>
            <DialogDescription className="break-keep">
              {novelTitle} · {episodeLabel}
            </DialogDescription>
          </DialogHeader>

          <DialogBody scrollLabel="소장 안내" className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm break-keep text-muted-foreground">
                <span>
                  클로버 <span className="font-semibold text-foreground tabular-nums">{price.toLocaleString()}</span>개를 써요
                </span>
                {balance !== undefined && (
                  <>
                    <span aria-hidden>·</span>
                    <span className="inline-flex items-center gap-1.5">
                      남은 클로버
                      <CloverBalance balance={balance} isInsufficient={isInsufficient} />
                    </span>
                  </>
                )}
              </p>
              {isInsufficient && (
                <p className="text-sm break-keep text-foreground">
                  {shortage !== undefined && shortage > 0
                    ? `클로버가 ${shortage.toLocaleString()}개 모자라요. 클로버를 채운 뒤 다시 소장해 주세요.`
                    : "클로버가 모자라요. 클로버를 채운 뒤 다시 소장해 주세요."}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-1.5 rounded-lg border border-border p-3 text-xs text-pretty break-keep text-muted-foreground">
              <p className="text-foreground">구매한 화는 공개가 유지되는 동안 볼 수 있어요.</p>
              <p>
                보기 시작한 뒤에는 구매를 취소할 수 없고, 게시자의 공개 철회·탈퇴나 원작 제한·운영 조치로 공개가 끝나도
                열람에 쓴 클로버는 돌려드리지 않아요(운영자의 잘못으로 끝난 경우는 제외). 게시자가 소설을 삭제하면 클로버가
                자동으로 돌아와요.
                {freeChapterCount > 0 && ` 앞 ${freeChapterCount}화는 무료로 미리 볼 수 있어요.`}
              </p>
            </div>

            {notice !== undefined && (
              <p role="alert" className="text-sm break-keep text-destructive-text">
                {notice}
              </p>
            )}
          </DialogBody>

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
                aria-disabled={purchase.isPending}
                className="aria-disabled:opacity-65"
                onClick={() => void handleConfirm()}
              >
                소장하기
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
