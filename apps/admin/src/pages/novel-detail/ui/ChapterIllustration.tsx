import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ImageOff } from "lucide-react";
import { useState } from "react";

import type { AdminNovelIllustration } from "@/entities/admin-novel";

import { illustrationAlt, illustrationFrameStyle, ILLUSTRATION_SOURCE_LABELS } from "../lib/chapterIllustrations";
import { NovelIllustrationTakedownConfirmModal } from "./NovelIllustrationTakedownConfirmModal";

/** 글 속 그림의 높이 상한(web 의 독자 화면과 같은 값) — 운영자가 독자에게 나가는 크기 그대로 본다. */
const ILLUSTRATION_MAX_HEIGHT_PX = 320;

/**
 * 공개본 화 펼침의 그림 한 장 — 독자 화면처럼 문단 사이 제자리에 서고, 아래 한 줄에 출처·자산 id·"그림 내리기"를 둔다.
 * 내린 그림은 그림 대신 독자에게 보이는 사유 전문을, 원작이 이용제한 중이라 가려진 원작 그림은 그 사정을 적은 점선 상자로
 * 그린다. 가려진 원작 그림에도 내리기를 남긴다 — 원작 제한이 풀리면 다시 보이므로 그 그림만 영구히 내릴 길이 있어야 한다.
 */
export function ChapterIllustration({ illustration }: { illustration: AdminNovelIllustration }) {
  const isTakenDown = illustration.withheld === "taken_down";

  return (
    <div className="flex flex-col gap-1.5">
      {illustration.withheld === null && illustration.url !== null ? (
        // 재조회로 주소가 바뀌면 틀을 새로 세워 앞 주소의 실패 표시를 버린다.
        <IllustrationFrame key={illustration.url} illustration={illustration} url={illustration.url} />
      ) : (
        <WithheldNotice illustration={illustration} />
      )}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span>{ILLUSTRATION_SOURCE_LABELS[illustration.source]}</span>
        <span aria-hidden>·</span>
        <span title={illustration.assetId}>
          <span className="sr-only">자산 id </span>
          {illustration.assetId.slice(0, 8)}
        </span>
        {!isTakenDown && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ml-auto"
            aria-label={`${illustrationAlt(illustration)} 내리기`}
            onClick={() => void NovelIllustrationTakedownConfirmModal.call({ illustration })}
          >
            그림 내리기
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * 크기를 알면 원본 비율 틀, 모르면 고정 3:4 웰 — 둘 다 높이 상한 320px 이고 그림이 오기 전에 자리를 잡는다. 카드 위라 웰 면은
 * `secondary` 다(`muted` 는 카드와 같은 값이라 사라진다). 주소가 만료돼 못 그리면 같은 틀 안에 문구만 둔다 — 화를 다시
 * 부르지 않는다(실패한 그림을 다시 받으려고 재조회하면 실패가 끝없이 되풀이될 수 있다).
 */
function IllustrationFrame({ illustration, url }: { illustration: AdminNovelIllustration; url: string }) {
  const [isBroken, setIsBroken] = useState(false);
  const sizedStyle = illustrationFrameStyle(illustration.width, illustration.height, ILLUSTRATION_MAX_HEIGHT_PX);

  return (
    <div
      className={cn(
        "flex items-center justify-center self-start overflow-hidden rounded-lg bg-secondary",
        sizedStyle === undefined && "aspect-3/4 h-80 max-w-3/4",
      )}
      style={sizedStyle}
    >
      {isBroken ? (
        <p className="px-3 text-center text-xs break-keep text-muted-foreground">그림을 불러오지 못했어요</p>
      ) : (
        <img
          src={url}
          alt={illustrationAlt(illustration)}
          loading="lazy"
          decoding="async"
          onError={() => setIsBroken(true)}
          className="size-full object-contain"
        />
      )}
    </div>
  );
}

/** 이미 처리된 상태라 경고색 없이 무채색 점선 상자로 둔다. 운영자 화면이라 사유를 자르지 않는다. */
function WithheldNotice({ illustration }: { illustration: AdminNovelIllustration }) {
  const isTakenDown = illustration.withheld === "taken_down";

  return (
    <div role="note" className="flex gap-2.5 rounded-lg border border-dashed border-border p-3 text-sm">
      <ImageOff aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="flex min-w-0 flex-col gap-1">
        <p className="font-medium break-keep text-foreground">
          {isTakenDown ? "운영자가 내린 그림" : "원작 작품이 이용제한 중이라 독자에게 가려진 원작 그림"}
        </p>
        {isTakenDown ? (
          <>
            {!!illustration.withheldReason && (
              <p className="whitespace-pre-wrap break-keep text-foreground wrap-anywhere">{illustration.withheldReason}</p>
            )}
            <p className="break-keep text-xs text-muted-foreground">
              독자에게는 그림 대신 이 사유가 보여요(읽기 화면 판형 안에서는 세 줄까지).
            </p>
          </>
        ) : (
          <p className="break-keep text-xs text-muted-foreground">
            원작 이용제한이 풀리면 다시 보여요. 이 그림만 영구히 내리려면 그림 내리기를 쓰세요.
          </p>
        )}
      </div>
    </div>
  );
}
