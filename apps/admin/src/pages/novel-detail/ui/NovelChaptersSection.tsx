import { Button } from "@ai-character-chat/ui/components/button";
import { ChevronDown } from "lucide-react";
import { Fragment, useId, useState } from "react";

import {
  useNovelChapterQuery,
  type AdminNovelChapterResponse,
  type AdminNovelDetailResponse,
} from "@/entities/admin-novel";
import { formatCount } from "@/shared/lib/format/formatCount";
import { QueryState } from "@/shared/ui/QueryState";

import { chapterEditions, isEditionIgnored } from "../lib/chapterEditions";
import { illustrationKey, illustrationSpots } from "../lib/chapterIllustrations";
import { ChapterEditionPicker } from "./ChapterEditionPicker";
import { ChapterIllustration } from "./ChapterIllustration";

type NovelChapter = AdminNovelDetailResponse["chapters"][number];

type NovelChaptersSectionProps = {
  novelId: string;
  chapters: NovelChapter[];
};

/** 공개본 화 목록. 행마다 지금 가격(무료·유료 화의 지금 표준가)과 판을 보인다. 본문은 상세 응답에 없어 화를 펼칠 때 그 화만 불러온다 — 한 번에 하나만 펼친다(5천 자 남짓한 화 여럿이
 * 한꺼번에 열리면 아래 심사·신고 칸이 멀리 밀린다). */
export function NovelChaptersSection({ novelId, chapters }: NovelChaptersSectionProps) {
  const [openChapterId, setOpenChapterId] = useState<string | null>(null);

  return (
    <section
      aria-labelledby="novel-chapters-heading"
      className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6"
    >
      <div className="flex flex-col gap-1">
        <h2 id="novel-chapters-heading" className="text-lg font-semibold text-foreground">
          공개본 화
        </h2>
        <p className="break-keep text-xs text-muted-foreground">
          독자에게 나가는 공개 시점 사본이에요. 게시자가 고친 뒤 다시 공개하면 판이 올라가요.
        </p>
      </div>
      {chapters.length === 0 ? (
        <p className="text-sm text-muted-foreground">공개된 화가 없어요.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
          {chapters.map((chapter) => (
            <ChapterRow
              key={chapter.id}
              novelId={novelId}
              chapter={chapter}
              isOpen={openChapterId === chapter.id}
              onToggle={() => setOpenChapterId((current) => (current === chapter.id ? null : chapter.id))}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

type ChapterRowProps = {
  novelId: string;
  chapter: NovelChapter;
  isOpen: boolean;
  onToggle: () => void;
};

function ChapterRow({ novelId, chapter, isOpen, onToggle }: ChapterRowProps) {
  const bodyId = useId();

  return (
    <li className="flex flex-col">
      <Button
        type="button"
        variant="ghost"
        aria-expanded={isOpen}
        aria-controls={isOpen ? bodyId : undefined}
        onClick={onToggle}
        className="h-auto min-h-11 w-full justify-start gap-3 rounded-none px-3 py-2 text-left whitespace-normal hover:bg-secondary"
      >
        <span className="w-10 shrink-0 text-sm font-semibold tabular-nums text-muted-foreground">{chapter.ordinal}화</span>
        <span className="min-w-0 flex-1 break-keep text-sm font-medium text-foreground wrap-anywhere">
          {chapter.title || "(제목 없음)"}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {chapter.price === 0 ? "무료" : `${formatCount(chapter.price)}클로버`} · {chapter.edition}판
        </span>
        <ChevronDown aria-hidden className={isOpen ? "rotate-180 motion-safe:transition-transform" : "motion-safe:transition-transform"} />
      </Button>
      {isOpen && (
        <div id={bodyId} className="border-t border-border px-3 py-4">
          <ChapterBody novelId={novelId} chapterId={chapter.id} />
        </div>
      )}
    </li>
  );
}

/**
 * 펼친 화 하나. 판이 둘 이상이면 머리에 판 고르기를 두고, 고른 판을 그 판을 산 회원이 보는 그대로 그린다(그림마다 내리기 버튼도
 * 그대로 — 그림 내림은 판과 무관하게 같은 파일이 쓰인 모든 판에서 내려간다).
 *
 * 판 목록은 늘 지금 판 응답에서 읽는다 — 고른 판 응답에서 읽으면 그 판을 받는 동안(데이터가 빈다)과 그 판을 못 불러온 동안 고르기가
 * 사라져 방금 누른 고르기에서 포커스가 떨어지고 지금 판으로 돌아갈 길도 없어진다. 고른 판이 지금 판이면 두 쿼리가 같은 키라 요청은
 * 하나다.
 */
function ChapterBody({ novelId, chapterId }: { novelId: string; chapterId: string }) {
  // `null` = 지금 판. 지금 판을 고르면 번호 대신 `null` 로 둔다 — 지금 판 응답과 같은 캐시를 써 요청이 겹치지 않는다.
  const [pickedEdition, setPickedEdition] = useState<number | null>(null);
  const currentQuery = useNovelChapterQuery(novelId, chapterId, null);
  const chapterQuery = useNovelChapterQuery(novelId, chapterId, pickedEdition);
  const editions = currentQuery.data ? chapterEditions(currentQuery.data) : [];
  const currentEdition = editions.find((item) => item.current)?.edition;
  const isIgnored = isEditionIgnored(pickedEdition, chapterQuery.data?.edition);
  const shownEdition = isIgnored ? currentEdition : (pickedEdition ?? currentEdition);
  const isPastEdition =
    !isIgnored && pickedEdition !== null && currentEdition !== undefined && pickedEdition !== currentEdition;

  return (
    <div className="flex flex-col gap-4">
      {editions.length > 1 && shownEdition !== undefined && (
        <ChapterEditionPicker
          editions={editions}
          value={shownEdition}
          onValueChange={(edition) => setPickedEdition(edition === currentEdition ? null : edition)}
        />
      )}
      {isIgnored && (
        <p role="status" className="break-keep text-sm text-muted-foreground">
          이 판을 불러오지 못해 지금 판을 보여요.
        </p>
      )}
      {isPastEdition && (
        <p className="break-keep rounded-lg bg-secondary p-3 text-sm text-foreground">
          지금 판이 아니에요. 이 판을 산 회원만 이 판을 읽어요. 그림을 내리면 모든 판에서 내려가요.
        </p>
      )}
      <QueryState query={chapterQuery} surface="card" errorMessage="이 화의 공개본을 불러오지 못했어요.">
        {(chapter) => <ChapterText chapter={chapter} />}
      </QueryState>
    </div>
  );
}

/** 작가의 말과 문단. 그림은 독자 화면처럼 그 문단의 앞·뒤 제자리에 선다 — 그림이 없으면 글만이다. */
function ChapterText({ chapter }: { chapter: AdminNovelChapterResponse }) {
  const spot = illustrationSpots(chapter);

  return (
    <div className="flex max-w-prose flex-col gap-4">
      {!!chapter.authorNote && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium text-foreground">작가의 말</h3>
          <p className="whitespace-pre-wrap break-keep rounded-lg bg-secondary p-3 text-sm text-foreground wrap-anywhere">
            {chapter.authorNote}
          </p>
        </div>
      )}
      <div className="flex flex-col gap-3 text-sm leading-relaxed text-foreground">
        {chapter.paragraphs.map((paragraph, index) => (
          // 문단은 공개본 안에서 순서만으로 정체가 정해지고 다시 정렬되지 않아 순번이 곧 키다.
          <Fragment key={index}>
            {spot("before", index).map((illustration) => (
              <ChapterIllustration key={illustrationKey(illustration)} illustration={illustration} />
            ))}
            <p className="whitespace-pre-wrap break-keep wrap-anywhere">{paragraph}</p>
            {spot("after", index).map((illustration) => (
              <ChapterIllustration key={illustrationKey(illustration)} illustration={illustration} />
            ))}
          </Fragment>
        ))}
      </div>
    </div>
  );
}
