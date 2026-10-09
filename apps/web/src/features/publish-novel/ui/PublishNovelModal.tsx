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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Check } from "lucide-react";
import { useId, useState } from "react";

import { useCloverPricingQuery } from "@/entities/clover";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { toPublishPriceSentence } from "../model/publicationView";

type PublishNovelModalProps = {
  /** 처음 공개인가, 이미 공개한(또는 거둔) 것을 다시 내는가 — 제목과 실행 문구가 갈린다. */
  mode: "publish" | "republish";
  /** "N화까지"에서 고를 수 있는 범위(`toPublishRange`). 아래 끝이 위 끝과 같으면 고를 것이 없어 글로만 보인다. */
  range: { min: number; max: number };
  chapterCount: number;
};

/** 노벨 공개 확인. 1화부터 이어진 화만 공개하므로 고르는 것은 "몇 화까지" 하나다 — 띄엄띄엄 고르는 모양 자체를 두지
 * 않는다. 기본값은 고를 수 있는 마지막 화이고, 다시 공개에서는 지금 공개한 범위보다 줄일 수 없다(줄이는 길은 마지막
 * 묶음 삭제나 거두기다). 확인 목록은 색 없는 체크 글리프로 공개하면 무엇이 일어나는지를 미리 말한다.
 *
 * 고른 끝 화를 돌려준다(취소면 `undefined`). 실제 요청은 호출부가 화 하나씩 보낸다(`usePublishNovelRun`) — 모달은
 * 바로 닫히고 공개 절이 "확인 중 · n/N화"를 그린다. 공개 화면의 페이지·보드에 마운트한다(루트에 두면 첫 화면 번들이
 * 커진다). */
export const PublishNovelModal = createCallable<PublishNovelModalProps, number | undefined>(
  ({ call, mode, range, chapterCount }) => {
    const selectId = useId();
    const [target, setTarget] = useState(range.max);
    const pricing = useCloverPricingQuery().data;
    const isFixed = range.min === range.max;
    const title = mode === "publish" ? "노벨에 공개하기" : "다시 공개하기";
    const options = Array.from({ length: range.max - range.min + 1 }, (_, index) => range.min + index);

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(undefined)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="break-keep">
              로그인한 회원 누구나 읽을 수 있어요. 1화부터 이어진 화만 공개할 수 있어요.
            </DialogDescription>
          </DialogHeader>

          <DialogBody className="flex flex-col gap-5">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-foreground tabular-nums">
              {isFixed ? (
                <span>1~{range.max}화</span>
              ) : (
                <>
                  <label htmlFor={selectId}>1화부터</label>
                  <Select value={String(target)} onValueChange={(value) => setTarget(Number(value))}>
                    <SelectTrigger id={selectId} className="w-28" aria-label="공개할 마지막 화">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((ordinal) => (
                        <SelectItem key={ordinal} value={String(ordinal)}>
                          {ordinal}화까지
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              )}
              <span className="text-muted-foreground">· {chapterCount}화 중</span>
            </div>

            <ul className="flex flex-col gap-2 text-sm break-keep text-muted-foreground">
              {[
                "공개하기 전에 제목·소개·화 본문·작가의 말을 자동으로 확인해요.",
                "공개한 뒤 고친 내용은 ‘다시 공개’해야 노벨에 반영돼요.",
                `${toPublishPriceSentence(
                  pricing === undefined
                    ? undefined
                    : { freeChapterCount: pricing.novelFreeChapterCount, chapterPrice: pricing.novelReadCost },
                )} 나는 언제나 무료로 읽어요.`,
                "표지는 원작 그림으로 보여요.",
              ].map((line) => (
                <li key={line} className="flex gap-2">
                  <Check aria-hidden className="mt-0.5 size-4 shrink-0" />
                  <span>{line}</span>
                </li>
              ))}
            </ul>

            <p className="text-sm break-keep text-muted-foreground">공개를 거두면 소장한 회원도 더 볼 수 없게 돼요.</p>
          </DialogBody>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end(undefined)}>
              취소
            </Button>
            <Button type="button" onClick={() => call.end(isFixed ? range.max : target)}>
              {(isFixed ? range.max : target).toLocaleString()}화까지 공개하기
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
