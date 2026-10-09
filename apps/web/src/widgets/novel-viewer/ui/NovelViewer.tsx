import { SheetTitle } from "@ai-character-chat/ui/components/sheet";
import { useQueryClient } from "@tanstack/react-query";
import { useId } from "react";

import {
  EpisodeTocList,
  novelKeys,
  NovelReadProgressSummary,
  saveReadingPosition,
  sendReadingPositionKeepalive,
  toNovelReadProgress,
  type NovelChapterResponse,
  type NovelChapterSummary,
  type NovelDetailResponse,
} from "@/entities/novel";

import { withChapterReadingPosition } from "../lib/readingPositionCache";
import { toChapterSavedReadingPosition } from "../lib/savedReadingPosition";
import type { ReadingPositionStore } from "../model/viewerSource";
import { EpisodeReader } from "./EpisodeReader";
import { ViewerTocSheet } from "./ViewerTocSheet";

type NovelViewerProps = {
  novel: NovelDetailResponse;
  /** 지금 화의 목차 정보(제목·요약·작가의 말·읽음). 화 조회 응답에는 이것들이 없다. */
  summary: NovelChapterSummary;
  /** 지금 화의 본문. 문단은 서버가 나눈 그대로 쓴다. */
  chapter: NovelChapterResponse;
};

/** 내 소설의 화 읽기 화면(`/novels/$novelId/episodes/$chapterId`). 읽기 화면 자체는 `EpisodeReader` 이고, 여기서는
 * 소유자 응답을 그 화면의 모양으로 옮기고 읽은 자리를 소유자 API·캐시에 잇는다. 목차는 읽은 정도와 읽음 표식을
 * 보인다. */
export function NovelViewer({ novel, summary, chapter }: NovelViewerProps) {
  const queryClient = useQueryClient();
  const progressId = useId();
  const revisionId = chapter.revision.id;
  // 화마다 읽던 자리가 상세에 실려 온다 — 마지막으로 읽은 화가 아니어도 그 화의 자리로 연다.
  const { saved, isAbsenceKnown } = toChapterSavedReadingPosition(summary, novel.lastRead);

  const readingPosition: ReadingPositionStore = {
    saved,
    isAbsenceKnown,
    wasFinished: summary.finishedReading,
    save: (position) => saveReadingPosition(novel.id, chapter.id, { ...position, revisionId }),
    sendKeepalive: (position) => sendReadingPositionKeepalive(novel.id, chapter.id, { ...position, revisionId }),
    onLeave(lastRecorded, settled) {
      if (lastRecorded !== undefined) {
        queryClient.setQueryData<NovelDetailResponse>(novelKeys.detail(novel.id), (detail) =>
          withChapterReadingPosition(detail, chapter.id, { ...lastRecorded, revisionId }),
        );
      }
      void settled.then(() => queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) }));
    },
  };

  return (
    <EpisodeReader
      route="owner"
      novel={novel}
      episode={{ ...summary, paragraphs: chapter.revision.paragraphs }}
      readingPosition={readingPosition}
      renderToc={(sheet) => (
        <ViewerTocSheet
          {...sheet}
          descriptionId={progressId}
          heading={
            <NovelReadProgressSummary
              heading={<SheetTitle>목차</SheetTitle>}
              progress={toNovelReadProgress(novel.chapters)}
              labelId={progressId}
            />
          }
        >
          <EpisodeTocList
            novelId={novel.id}
            chapters={novel.chapters}
            lastReadChapterId={novel.lastRead?.chapterId}
            currentChapterId={chapter.id}
            surface="sheet"
            onNavigate={() => sheet.onOpenChange(false)}
          />
        </ViewerTocSheet>
      )}
    />
  );
}
