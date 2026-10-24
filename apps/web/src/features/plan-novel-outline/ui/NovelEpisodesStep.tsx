import { useId } from "react";

import { useNovelOutlineQuery, type NovelDetailResponse } from "@/entities/novel";

import { toManuscriptStatuses } from "../model/episodeStatus";
import { toEpisodeOrdinals } from "../model/outlineStatus";

import { EpisodeRowList } from "./EpisodeRowList";

type NovelEpisodesStepProps = {
  novel: NovelDetailResponse;
  onOpenEpisode: (episodeKey: string) => void;
  onOpenChapter: (chapterId: string) => void;
};

/**
 * 구성 3단계 "화별 장면·원고" — 승인한 전체 구성안의 화 목록. 화마다 장면 구성안·원고 상태를 보이고, "열기"로 그 화 화면(장면 구성안
 * 만들기·고치기·승인, 원고 쓰기)에 들어간다. 장면 구성안과 원고는 승인한 구성안의 화로만 만들므로, 승인본 위에 고친 초안이 있어도 이
 * 목록은 승인본이다.
 *
 * 전체 구성안 조회는 2단계와 같은 쿼리다 — 불러오는 중·실패는 2단계가 말하므로 여기서는 되풀이하지 않는다.
 */
export function NovelEpisodesStep({ novel, onOpenEpisode, onOpenChapter }: NovelEpisodesStepProps) {
  const headingId = useId();
  const query = useNovelOutlineQuery(novel.id, { enabled: true });
  const state = query.data;
  if (state === undefined) return null;
  const approved = state.approved;
  const ordinals = approved === null ? [] : toEpisodeOrdinals(approved.episodes, novel.chapters);
  const manuscripts = approved === null ? [] : toManuscriptStatuses(approved.episodes);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h3 id={headingId} className="text-lg font-semibold text-foreground">
        화별 장면·원고
      </h3>
      {approved === null ? (
        <p className="text-sm break-keep text-muted-foreground">
          전체 구성안을 승인하면 화마다 장면 구성안을 만들어 고친 뒤 원고를 써요.
        </p>
      ) : (
        <>
          <p className="text-sm break-keep text-muted-foreground">
            화마다 장면 구성안을 만들어 승인한 뒤, 앞 화부터 차례로 원고를 써요.
          </p>
          {state.draft !== null && (
            <p className="text-sm break-keep text-muted-foreground">
              아래는 승인한 구성안의 화예요. 고친 초안은 승인해야 여기에 이어져요.
            </p>
          )}
          {approved.stale && (
            <p className="rounded-lg border border-border px-4 py-3 text-sm break-keep text-foreground">
              승인한 전체 구성안이 낡아 장면 구성안을 만들거나 원고를 쓸 수 없어요. 위에서 전체 구성안을 바로잡아주세요.
            </p>
          )}
          <EpisodeRowList
            rows={approved.episodes.map((episode, index) => ({
              key: episode.key,
              ordinal: ordinals[index] ?? index + 1,
              title: episode.title,
              sceneOutline: episode.sceneOutline,
              manuscript: manuscripts[index] ?? { kind: "waiting" },
            }))}
            onOpenEpisode={onOpenEpisode}
            onOpenChapter={onOpenChapter}
          />
        </>
      )}
    </section>
  );
}
