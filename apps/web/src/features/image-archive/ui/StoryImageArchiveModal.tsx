import type { ReactNode } from "react";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Lock } from "lucide-react";

import {
  useStoryImageArchiveQuery,
  type LockedArchiveTile,
  type StoryImageArchiveGroup,
  type UnlockedArchiveTile,
} from "@/entities/story-image-archive";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { expandAuthorMacros, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

type StoryImageArchiveModalProps = {
  storyId: string;
  /**
   * 해금 힌트 속 `{{user}}` 이름 — 보관함은 작품 단위지만 여는 곳이 언제나 대화방이라 그 방의 이름을 쓴다. 인물·장면
   * 이름은 바꾸지 않는다: 글 속 그림 태그가 그 이름을 그대로 가리키는 키라, 화면 이름만 바뀌면 작가가 쓴 태그와
   * 어긋나 보인다.
   */
  macroNames: AuthorMacroNames;
};

// 스토리 방의 "더보기 > 이미지 보관함". 캐릭터 보관함(ImageArchiveModal)과 응답 모양·표시가 달라(인물별 묶음, 원본
// 비율, 힌트) 따로 둔다 — 한 컴포넌트에서 분기하면 캐릭터 보관함의 표시가 함께 흔들린다.
export const StoryImageArchiveModal = createCallable<StoryImageArchiveModalProps, void>(({ call, storyId, macroNames }) => {
  const isOpen = !call.ended;
  const archiveQuery = useStoryImageArchiveQuery(storyId, isOpen);

  return (
    <Dialog open={isOpen} onOpenChange={(next) => !next && call.end()}>
      {/* 칸이 50개까지라 길어진다 — 그림 묶음을 `DialogBody` 에 넣어 그것만 스크롤하고 제목·닫기는 위에 남긴다.
          보관함 칸은 버튼이 아니라 포커스할 것이 하나도 없으므로, 본문 자체를 Tab 정지로 둬야 키보드로 스크롤할 수 있다. */}
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>이미지 보관함</DialogTitle>
          <DialogDescription className="break-keep">
            대화 중 만난 이미지를 모아봤어요. 아직 못 본 이미지는 흐리게 보여요.
          </DialogDescription>
        </DialogHeader>

        <DialogBody scrollLabel="보관함 이미지">
          <StoryImageArchiveBody query={archiveQuery} macroNames={macroNames} />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
});

/** 네 상태(로딩·오류·빈 목록·묶음)가 배타적이라 early return 으로 순서를 강제한다. */
function StoryImageArchiveBody({
  query,
  macroNames,
}: {
  query: ReturnType<typeof useStoryImageArchiveQuery>;
  macroNames: AuthorMacroNames;
}) {
  if (query.isPending) {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="aspect-3/4 animate-pulse rounded-lg bg-secondary" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    // 404 는 작품이 없거나(내려감·발행본 없음) 이 사용자가 볼 수 없는 작품이다 — 다시 시도해도 같다.
    return (
      <p className="py-4 text-center text-sm break-keep text-destructive-text">
        {query.error.status === 404
          ? "볼 수 없는 작품이에요."
          : "불러오지 못했어요. 잠시 후 다시 시도해주세요."}
      </p>
    );
  }

  const { groups, unlockedCount, totalCount } = query.data;
  if (totalCount === 0) {
    return (
      <p className="py-4 text-center text-sm break-keep text-muted-foreground">
        이 작품에는 보관함에 모을 이미지가 없어요.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-xs text-muted-foreground">
        {totalCount}장 중 {unlockedCount}장을 모았어요
      </p>
      {groups.map((group, index) => (
        // 같은 이름의 인물이 떨어져 올 수 있어(toStoryImageArchiveView) 이름이 아니라 첫 칸 id 로 묶음을 가른다.
        <PersonGroup key={group.tiles[0]?.id ?? index} group={group} macroNames={macroNames} />
      ))}
    </div>
  );
}

function PersonGroup({ group, macroNames }: { group: StoryImageArchiveGroup; macroNames: AuthorMacroNames }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-sm font-medium break-keep text-foreground">{group.personName}</h3>
      {/* items-start: 비율이 다른 그림이 한 줄에 서도 짧은 칸을 늘리지 않는다(늘리면 그림 아래 빈 면이 생긴다). */}
      <ul className="grid grid-cols-2 items-start gap-2 sm:grid-cols-3">
        {group.tiles.map((tile) => (
          <li key={tile.id}>
            {tile.kind === "unlocked" ? <UnlockedTile tile={tile} /> : <LockedTile tile={tile} macroNames={macroNames} />}
          </li>
        ))}
      </ul>
    </section>
  );
}

function UnlockedTile({ tile }: { tile: UnlockedArchiveTile }) {
  return (
    <figure className="flex flex-col gap-1">
      <TileFrame aspectRatio={tile.aspectRatio}>
        <img src={tile.imageUrl} alt={tile.alt} loading="lazy" decoding="async" className="size-full object-cover" />
      </TileFrame>
      {tile.sceneName !== "" && (
        <figcaption className="truncate text-xs text-muted-foreground">{tile.sceneName}</figcaption>
      )}
    </figure>
  );
}

/**
 * 블러본 위에 자물쇠와 힌트를 얹는다. 그림이 무엇이든 글자가 읽혀야 하므로 글자 아래에 무채색 반투명 면을 깐다 —
 * 테마를 따르는 `background` 면 위의 `foreground` 글자라 다크에서 순백이 되지 않고, 면을 칸 전체가 아니라 글자 둘레에만
 * 깔아 흐린 그림이 남아 보이게 한다.
 */
function LockedTile({ tile, macroNames }: { tile: LockedArchiveTile; macroNames: AuthorMacroNames }) {
  return (
    <TileFrame aspectRatio={tile.aspectRatio}>
      <img src={tile.imageUrl} alt={tile.alt} loading="lazy" decoding="async" className="size-full object-cover" />
      <div className="absolute inset-0 flex items-center justify-center p-2">
        <div className="flex max-w-full flex-col items-center gap-1 rounded-md bg-background/75 px-2.5 py-2 text-center text-foreground">
          <Lock aria-hidden className="size-4 shrink-0" />
          {tile.hint !== undefined && (
            <p className="text-xs break-keep wrap-break-word">
              <span className="sr-only">해금 힌트: </span>
              {expandAuthorMacros(tile.hint, macroNames)}
            </p>
          )}
        </div>
      </div>
    </TileFrame>
  );
}

/** 그림이 오기 전에 칸 높이를 잡는다 — 크기를 알면 원본 비율, 모르면 3:4. 다이얼로그 면 위라 빈 칸 면은 secondary 다. */
function TileFrame({ aspectRatio, children }: { aspectRatio: string | undefined; children: ReactNode }) {
  return (
    <div
      className={cn("relative overflow-hidden rounded-lg bg-secondary", aspectRatio === undefined && "aspect-3/4")}
      style={aspectRatio === undefined ? undefined : { aspectRatio }}
    >
      {children}
    </div>
  );
}
