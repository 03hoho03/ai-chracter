import type { components } from "@ai-character-chat/api-types";

export type StoryImageArchiveItem = components["schemas"]["StoryImageArchiveItem"];

/** 본 칸. 장면 이름은 본 칸에만 있다. */
export type UnlockedArchiveTile = {
  kind: "unlocked";
  id: string;
  imageUrl: string;
  sceneName: string;
  /** CSS `aspect-ratio` 값(`"768 / 1024"`). 크기를 모르면 undefined — 화면은 고정 3:4 칸으로 그린다. */
  aspectRatio: string | undefined;
  alt: string;
};

/** 아직 못 본 칸. 그림은 서버가 만든 블러본이고, 장면 이름은 무엇이 그려졌는지 미리 알려 주므로 싣지 않는다. */
export type LockedArchiveTile = {
  kind: "locked";
  id: string;
  imageUrl: string;
  /** 작가가 적은 해금 힌트. 비었으면 undefined — 화면은 자물쇠만 그린다. */
  hint: string | undefined;
  aspectRatio: string | undefined;
  alt: string;
};

export type StoryImageArchiveTile = UnlockedArchiveTile | LockedArchiveTile;

export type StoryImageArchiveGroup = {
  personName: string;
  tiles: StoryImageArchiveTile[];
};

export type StoryImageArchiveView = {
  groups: StoryImageArchiveGroup[];
  unlockedCount: number;
  totalCount: number;
};

/**
 * 보관함 응답을 인물별 묶음으로 바꾼다. 서버가 인물 순서 → 장면 순서로 정렬해 주므로 순서를 다시 매기지 않고, 연달아
 * 오는 같은 인물을 한 묶음으로 모은다(같은 이름의 인물이 따로 떨어져 오면 묶음도 따로다 — 작가가 이름을 겹쳐 쓴 경우라
 * 합치면 다른 인물의 칸이 섞인다).
 */
export function toStoryImageArchiveView(items: StoryImageArchiveItem[]): StoryImageArchiveView {
  const groups: StoryImageArchiveGroup[] = [];
  for (const item of items) {
    const tile = toTile(item);
    const last = groups.at(-1);
    if (last !== undefined && last.personName === item.personName) last.tiles.push(tile);
    else groups.push({ personName: item.personName, tiles: [tile] });
  }
  return {
    groups,
    unlockedCount: items.filter((item) => item.exposed).length,
    totalCount: items.length,
  };
}

function toTile(item: StoryImageArchiveItem): StoryImageArchiveTile {
  const aspectRatio = toAspectRatio(item.width, item.height);
  if (item.exposed) {
    const sceneName = item.sceneName.trim();
    return {
      kind: "unlocked",
      id: item.id,
      imageUrl: item.imageUrl,
      sceneName,
      aspectRatio,
      alt: sceneName ? `${item.personName} · ${sceneName}` : item.personName,
    };
  }
  // 못 본 칸의 장면 이름은 서버가 빈 문자열로 보내지만, 실수로 실려 와도 화면에 내지 않도록 여기서 버린다.
  const hint = item.unlockHint.trim();
  return {
    kind: "locked",
    id: item.id,
    imageUrl: item.imageUrl,
    hint: hint || undefined,
    aspectRatio,
    alt: `${item.personName}의 아직 보지 못한 그림`,
  };
}

function toAspectRatio(width: number | null | undefined, height: number | null | undefined): string | undefined {
  if (!width || !height || width <= 0 || height <= 0) return undefined;
  return `${width} / ${height}`;
}
