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
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { Check } from "lucide-react";
import { useId } from "react";
import { Controller, useForm, useWatch, type Control, type FieldErrors } from "react-hook-form";

import { useCloverPricingQuery } from "@/entities/clover";
import type { NovelPublicationStatus } from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { countCharacters } from "@/shared/lib/text/characterCount";
import { CharacterCount } from "@/shared/ui/CharacterCount";

import { toBuyerPolicyCopy } from "../model/buyerPolicyCopy";
import { toPublishPriceSentence, type PublishChoice } from "../model/publicationView";
import {
  CHANGE_SUMMARY_MAX_LENGTH,
  publishChoiceSchema,
  toPublishChoice,
  type PublishChoiceFormInput,
  type PublishChoiceFormValues,
} from "../model/publishChoiceSchema";
import { toPublishPriceRows, toRepublishOrdinals, type PublishPriceRow } from "../model/publishPricing";

type PublishNovelModalProps = {
  /** 처음 공개인가, 이미 공개한(또는 거둔) 것을 다시 내는가 — 제목과 실행 문구가 갈린다. */
  mode: "publish" | "republish";
  /** "N화까지"에서 고를 수 있는 범위(`toPublishRange`). 아래 끝이 위 끝과 같으면 고를 것이 없어 글로만 보인다. */
  range: { min: number; max: number };
  /** 모달을 연 때의 공개 상태 — 화 수, 첫 공개 승인 필요 여부, 화별 가격·다시 내는 고친 화를 여기서 읽는다. */
  status: NovelPublicationStatus;
  /** 노벨 정책 스위치가 켜졌을 때만 넘긴다 — 그때 새 화 가격과 다시 내는 화의 변경 요약을 받는다. 없으면 지금 화면 그대로다. */
  policyV2: { freeChapterCount: number } | undefined;
};

const MODE_TITLES: Record<PublishNovelModalProps["mode"], string> = {
  publish: "노벨에 공개하기",
  republish: "다시 공개하기",
};

/** 노벨 공개 확인. 1화부터 이어진 화만 공개하므로 고르는 것은 "몇 화까지" 하나다 — 띄엄띄엄 고르는 모양 자체를 두지
 * 않는다. 기본값은 고를 수 있는 마지막 화이고, 다시 공개에서는 지금 공개한 범위보다 줄일 수 없다(줄이는 길은 마지막
 * 묶음 삭제나 거두기다). 확인 목록은 색 없는 체크 글리프로 공개하면 무엇이 일어나는지를 미리 말한다.
 *
 * 노벨 정책 스위치가 켜져 있으면 두 칸이 더 생긴다. "화별 가격"은 새로 공개하는 화 중 앞 화 다음부터 화마다 무료·유료를
 * 고른다(기본 유료 — 무료로 낸 화는 다시 유료가 되지 않아 실수의 값이 무료 쪽이 크다). 줄마다 선택이 하나씩 켜져 있어
 * 기본 선택 칩(`primary` 솔리드)을 쓰면 화면에 솔리드 채움이 줄 수만큼 생기므로 무채 선택 칩(`neutral`)을 쓴다 — 이
 * 화면의 솔리드는 실행 버튼 하나다. 무료로 낸 적 있는 번호는 무료로 고정이고, 다시 내는 고친 화는 지금 가격을 글로만
 * 보인다. "변경 요약"은 다시 내는 고친 화마다 한 칸이다 — 그 화를 산 회원이 그 화의 판을 고를 때 보는 글이라 화마다
 * 다르다.
 *
 * 고른 것을 돌려준다(취소면 `undefined`). 실제 요청은 호출부가 화 하나씩 보낸다(`usePublishNovelRun`) — 모달은
 * 바로 닫히고 공개 절이 "확인 중 · n/N화"를 그린다. 공개 화면의 페이지·보드에 마운트한다(루트에 두면 첫 화면 번들이
 * 커진다).
 *
 * 첫 공개에 운영자 승인이 필요하면 무엇이 다른지를 설명 첫 줄에 먼저 말하고 실행 문구를 "1화 공개 신청하기"로 바꾼다.
 * 확인에 걸리는 시간은 정해진 값이 없어 약속하지 않는다. */
export const PublishNovelModal = createCallable<PublishNovelModalProps, PublishChoice | undefined>(
  ({ call, mode, range, status, policyV2 }) => {
    const selectId = useId();
    const pricing = useCloverPricingQuery().data;
    const form = useForm<PublishChoiceFormInput, unknown, PublishChoiceFormValues>({
      resolver: zodResolver(publishChoiceSchema),
      defaultValues: toDefaultValues({ range, status, policyV2 }),
    });
    const target = useWatch({ control: form.control, name: "targetOrdinal" });
    const isFixed = range.min === range.max;
    const reviewRequired = status.reviewRequired;
    const title = reviewRequired ? "노벨에 공개 신청하기" : MODE_TITLES[mode];
    const options = Array.from({ length: range.max - range.min + 1 }, (_, index) => range.min + index);
    const priceRows =
      policyV2 === undefined ? [] : toPublishPriceRows(status, { freeChapterCount: policyV2.freeChapterCount, targetOrdinal: target });
    const summaryOrdinals = policyV2 === undefined ? [] : toRepublishOrdinals(status);

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(undefined)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="break-keep">
              {reviewRequired && "첫 공개는 운영자가 1화를 확인한 뒤 독자에게 열려요. "}
              로그인한 회원 누구나 읽을 수 있어요. 1화부터 이어진 화만 공개할 수 있어요.
            </DialogDescription>
          </DialogHeader>

          <form
            noValidate
            className="flex min-h-0 flex-1 flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void form.handleSubmit((values) => call.end(toPublishChoice(values)))(event);
            }}
          >
            <DialogBody className="flex flex-col gap-5">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-foreground tabular-nums">
                {isFixed ? (
                  <span>{range.max === 1 ? "1화" : `1~${range.max}화`}</span>
                ) : (
                  <>
                    <label htmlFor={selectId}>1화부터</label>
                    <Controller
                      control={form.control}
                      name="targetOrdinal"
                      render={({ field }) => (
                        <Select value={String(field.value)} onValueChange={(value) => field.onChange(Number(value))}>
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
                      )}
                    />
                  </>
                )}
                <span className="text-muted-foreground">· {status.chapterCount}화 중</span>
              </div>

              {priceRows.length > 0 && (
                <PriceRows rows={priceRows} control={form.control} chapterPrice={pricing?.novelReadCost} />
              )}

              {summaryOrdinals.length > 0 && (
                <SummaryFields ordinals={summaryOrdinals} form={form} errors={form.formState.errors} />
              )}

              <ul className="flex flex-col gap-2 text-sm break-keep text-muted-foreground">
                {[
                  "공개하기 전에 제목·소개·화 본문·작가의 말을 자동으로 확인해요.",
                  "공개한 뒤 고친 내용은 ‘다시 공개’해야 노벨에 반영돼요.",
                  `${toPublishPriceSentence(
                    pricing === undefined
                      ? undefined
                      : {
                          freeChapterCount: pricing.novelFreeChapterCount,
                          chapterPrice: pricing.novelReadCost,
                          isPolicyV2Enabled: policyV2 !== undefined,
                        },
                  )} 나는 언제나 무료로 읽어요.`,
                  "지금은 열람 수익을 게시자에게 나누지 않아요.",
                  "표지는 원작 그림으로 보여요.",
                ].map((line) => (
                  <li key={line} className="flex gap-2">
                    <Check aria-hidden className="mt-0.5 size-4 shrink-0" />
                    <span>{line}</span>
                  </li>
                ))}
              </ul>

              <p className="text-sm break-keep text-muted-foreground">{toBuyerPolicyCopy(pricing).publishWithdrawNote}</p>
            </DialogBody>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => call.end(undefined)}>
                취소
              </Button>
              <Button type="submit">
                {reviewRequired ? "1화 공개 신청하기" : `${(isFixed ? range.max : target).toLocaleString()}화까지 공개하기`}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);

/** 가격 줄은 고를 수 있는 끝 화까지 미리 만들어 둔다 — 끝 화를 줄였다 늘려도 고른 값이 남는다. 요약 칸은 다시 내는 고친
 * 화마다 빈 글로 시작한다. */
function toDefaultValues({
  range,
  status,
  policyV2,
}: Pick<PublishNovelModalProps, "range" | "status" | "policyV2">): PublishChoiceFormInput {
  if (policyV2 === undefined) return { targetOrdinal: range.max, prices: [], summaries: [] };
  const rows = toPublishPriceRows(status, { freeChapterCount: policyV2.freeChapterCount, targetOrdinal: range.max });
  return {
    targetOrdinal: range.max,
    prices: rows.flatMap((row) => (row.kind === "choice" ? [{ ordinal: row.ordinal, isFree: false }] : [])),
    summaries: toRepublishOrdinals(status).map((ordinal) => ({ ordinal, text: "" })),
  };
}

/** "화별 가격" — 새 화는 무료·유료 칩, 무료 고정 번호와 다시 내는 화는 글. 줄 순서는 화 번호다. */
function PriceRows({
  rows,
  control,
  chapterPrice,
}: {
  rows: PublishPriceRow[];
  control: Control<PublishChoiceFormInput, unknown, PublishChoiceFormValues>;
  /** 지금 유료 화 가격. 가격 응답이 아직 없으면 숫자를 말하지 않는다. */
  chapterPrice: number | undefined;
}) {
  const headingId = useId();
  const prices = useWatch({ control, name: "prices" });
  const paidLabel = chapterPrice === undefined ? "유료" : `유료 · 클로버 ${chapterPrice.toLocaleString()}개`;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 id={headingId} className="text-sm font-medium text-foreground">
        화별 가격
      </h3>
      <ul className="flex flex-col gap-2">
        {rows.map((row) => (
          <li key={row.ordinal} className="flex min-h-8 flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
            <span id={`${headingId}-${row.ordinal}`} className="text-foreground tabular-nums">
              {row.ordinal}화
            </span>
            {row.kind === "choice" && (
              <Controller
                control={control}
                name={`prices.${prices.findIndex((price) => price.ordinal === row.ordinal)}.isFree`}
                render={({ field }) => (
                  <ToggleGroup
                    type="single"
                    variant="neutral"
                    size="sm"
                    aria-labelledby={`${headingId}-${row.ordinal}`}
                    value={field.value ? "free" : "paid"}
                    onValueChange={(value) => {
                      // 단일 토글 그룹은 고른 칸을 다시 누르면 빈 값을 보낸다 — 가격은 늘 하나라 해제를 받지 않는다.
                      if (value === "free" || value === "paid") field.onChange(value === "free");
                    }}
                  >
                    <ToggleGroupItem value="free">무료</ToggleGroupItem>
                    <ToggleGroupItem value="paid">{paidLabel}</ToggleGroupItem>
                  </ToggleGroup>
                )}
              />
            )}
            {row.kind === "locked" && (
              <span className="break-keep text-muted-foreground">무료 고정 · 전에 무료로 공개한 번호예요</span>
            )}
            {row.kind === "kept" && (
              <span className="break-keep text-muted-foreground">
                {row.price === 0 ? "무료" : `유료 · 클로버 ${row.price.toLocaleString()}개`} · 지금 가격 그대로
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="text-xs break-keep text-muted-foreground">
        {/* 고를 줄이 없으면(다시 내는 화·무료 고정만) 고르는 일의 결과는 말할 것이 없다. */}
        {rows.some((row) => row.kind === "choice") && "무료로 공개한 화는 나중에 유료로 바꿀 수 없어요. "}
        유료 화 가격은 서비스 표준가를 따라요. 표준가가 바뀌면 그 뒤 소장부터 바뀐 값이에요.
      </p>
    </section>
  );
}

/** "변경 요약" — 다시 내는 고친 화마다 한 칸. 글자 수는 서버처럼 앞뒤 공백을 덜고 코드 포인트로 센다. */
function SummaryFields({
  ordinals,
  form,
  errors,
}: {
  ordinals: number[];
  form: ReturnType<typeof useForm<PublishChoiceFormInput, unknown, PublishChoiceFormValues>>;
  errors: FieldErrors<PublishChoiceFormInput>;
}) {
  const headingId = useId();
  const summaries = useWatch({ control: form.control, name: "summaries" });

  return (
    <section aria-labelledby={headingId} aria-describedby={`${headingId}-help`} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h3 id={headingId} className="text-sm font-medium text-foreground">
          변경 요약
        </h3>
        <p id={`${headingId}-help`} className="text-xs break-keep text-muted-foreground">
          고친 화마다 바뀐 것을 짧게 적어 주세요. 그 화를 산 회원이 판을 고를 때 공개 날짜와 함께 보여요.
        </p>
      </div>
      {ordinals.map((ordinal, index) => {
        const fieldId = `${headingId}-${ordinal}`;
        const error = errors.summaries?.[index]?.text;
        const describedBy = [`${fieldId}-count`, error ? `${fieldId}-error` : undefined]
          .filter((id) => id !== undefined)
          .join(" ");
        return (
          <div key={ordinal} className="flex flex-col gap-1.5">
            <Label htmlFor={fieldId}>{ordinal}화에서 바뀐 것</Label>
            <Textarea
              id={fieldId}
              rows={2}
              placeholder="예: 결말 문단의 대사를 고쳤어요"
              aria-invalid={!!error}
              aria-describedby={describedBy}
              {...form.register(`summaries.${index}.text`)}
            />
            <CharacterCount
              id={`${fieldId}-count`}
              count={countCharacters((summaries[index]?.text ?? "").trim())}
              max={CHANGE_SUMMARY_MAX_LENGTH}
            />
            {error && (
              <p id={`${fieldId}-error`} role="alert" className="text-xs break-keep text-destructive-text">
                {error.message}
              </p>
            )}
          </div>
        );
      })}
    </section>
  );
}
