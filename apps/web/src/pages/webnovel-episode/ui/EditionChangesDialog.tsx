import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Link } from "@tanstack/react-router";

import type { EditionInfo } from "@/entities/webnovel";

type EditionChangesDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  novelId: string;
  chapterId: string;
  ordinal: number;
  purchased: EditionInfo;
  latest: EditionInfo;
  /** 지금 읽는 판이 구매 당시 판인가(아니면 최신 판). */
  isReadingPurchased: boolean;
  /** 닫을 때 포커스를 돌려줄 곳(연 "바뀐 내용" 버튼). 다이얼로그가 트리거 없이 열려 기본 복귀가 문서 처음으로 떨어진다. */
  returnFocusTo: () => HTMLElement | null;
};

/** "바뀐 내용" — 소장하신 뒤 고쳐진 화의 두 판(구매 당시 판·최신 판)을 공개 날짜와 작가의 변경 요약으로 보이고, 지금 읽지
 * 않는 판으로 가는 길을 낸다. 제목 아래 한 줄은 판형 안에 있어 길어지면 쪽 수가 바뀌므로, 날짜·요약은 판형 밖의 이
 * 다이얼로그가 맡는다.
 *
 * 서버는 이 두 판만 싣는다 — 사이에 고친 판이 있으면 최신 판의 요약은 마지막으로 고친 것만 말하므로 그렇다고 적는다.
 * 요약이 없는 판(첫 판·요약을 받기 전에 낸 판)은 요약 자리를 비우되, 최신 판은 "바뀐 내용"을 열고 들어온 자리라 비었다고
 * 말한다. 판을 고르는 것은 주소의 `edition` 이라 링크로 옮긴다(판이 바뀌면 읽기 화면이 새로 마운트돼 다이얼로그도 닫힌다).
 * 이 화면에 솔리드 채움은 없다 — 판 고르기는 같은 무게의 두 선택이라 outline 이다. */
export function EditionChangesDialog({
  open,
  onOpenChange,
  novelId,
  chapterId,
  ordinal,
  purchased,
  latest,
  isReadingPurchased,
  returnFocusTo,
}: EditionChangesDialogProps) {
  const hasEditionsBetween = latest.edition - purchased.edition > 1;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        onCloseAutoFocus={(event) => {
          // 판형이 바·쪽 넘김으로 `inert` 가 된 사이면 돌려줄 수 없어 기본 동작에 맡긴다(댓글 시트와 같다).
          const target = returnFocusTo();
          if (target === null || !target.isConnected || target.closest("[inert]") !== null) return;
          event.preventDefault();
          target.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle className="break-keep">{ordinal}화의 바뀐 내용</DialogTitle>
          <DialogDescription className="break-keep">
            소장하신 뒤 작가가 이 화를 고쳐 다시 공개했어요. 구매 당시 판과 최신 판 중에 골라 읽을 수 있어요.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-5">
          <ul className="flex flex-col gap-5">
            <EditionItem
              label="구매 당시 판"
              info={purchased}
              isReading={isReadingPurchased}
              emptySummary={undefined}
              link={{ novelId, chapterId, edition: purchased.edition }}
            />
            <EditionItem
              label="최신 판"
              info={latest}
              isReading={!isReadingPurchased}
              emptySummary="작가가 이 판에 변경 요약을 남기지 않았어요."
              link={{ novelId, chapterId, edition: undefined }}
            />
          </ul>
          {hasEditionsBetween && (
            <p className="text-xs break-keep text-muted-foreground">
              두 판 사이에 고친 판이 더 있어요. 최신 판의 요약은 마지막으로 고친 내용만 말해요.
            </p>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

function EditionItem({
  label,
  info,
  isReading,
  emptySummary,
  link,
}: {
  label: string;
  info: EditionInfo;
  isReading: boolean;
  /** 요약이 없을 때 대신 쓸 말. 없으면 그 자리를 비운다. */
  emptySummary: string | undefined;
  /** 이 판의 주소 — 최신 판은 `edition` 없이 연다. */
  link: { novelId: string; chapterId: string; edition: number | undefined };
}) {
  return (
    <li className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="text-sm text-muted-foreground tabular-nums">{info.dateLabel} 공개</p>
        {isReading && (
          <span className="inline-flex w-fit items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
            읽는 중
          </span>
        )}
      </div>
      {info.summary !== undefined ? (
        <p className="text-sm whitespace-pre-line break-keep text-foreground">{info.summary}</p>
      ) : (
        emptySummary !== undefined && <p className="text-sm break-keep text-muted-foreground">{emptySummary}</p>
      )}
      {!isReading && (
        <Button asChild variant="outline" size="sm" className="w-fit">
          <Link
            to="/webnovels/$novelId/episodes/$chapterId"
            params={{ novelId: link.novelId, chapterId: link.chapterId }}
            search={link.edition === undefined ? {} : { edition: link.edition }}
          >
            {label}으로 읽기
          </Link>
        </Button>
      )}
    </li>
  );
}
