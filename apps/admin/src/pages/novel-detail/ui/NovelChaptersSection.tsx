import { Button } from "@ai-character-chat/ui/components/button";
import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

import { useNovelChapterQuery, type AdminNovelDetailResponse } from "@/entities/admin-novel";
import { QueryState } from "@/shared/ui/QueryState";

type NovelChapter = AdminNovelDetailResponse["chapters"][number];

type NovelChaptersSectionProps = {
  novelId: string;
  chapters: NovelChapter[];
};

/** 공개본 화 목록. 본문은 상세 응답에 없어 화를 펼칠 때 그 화만 불러온다 — 한 번에 하나만 펼친다(5천 자 남짓한 화 여럿이
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
        <span className="shrink-0 text-xs text-muted-foreground">{chapter.edition}판</span>
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

function ChapterBody({ novelId, chapterId }: { novelId: string; chapterId: string }) {
  const chapterQuery = useNovelChapterQuery(novelId, chapterId);

  return (
    <QueryState query={chapterQuery} surface="card" errorMessage="이 화의 공개본을 불러오지 못했어요.">
      {(chapter) => (
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
              <p key={index} className="whitespace-pre-wrap break-keep wrap-anywhere">
                {paragraph}
              </p>
            ))}
          </div>
        </div>
      )}
    </QueryState>
  );
}
