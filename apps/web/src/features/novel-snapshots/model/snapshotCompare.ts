import type {
  NovelChapterSummary,
  NovelCharacterResponse,
  NovelDetailResponse,
  NovelSnapshotDetail,
} from "@/entities/novel";

/** 버전과 지금을 맞춘 화 한 줄. */
export type SnapshotChapterRow =
  /** 버전에도 지금도 있는 화. `isChanged` 는 본문 판·제목·작가의 말 중 하나라도 다른가다. */
  | {
      kind: "kept";
      chapterId: string;
      ordinal: number;
      isChanged: boolean;
      /** 버전 때 본문 판. 지금 판과 같으면 본문은 그대로다. */
      snapshotRevisionId: string | null;
      currentRevisionId: string;
      snapshotTitle: string | null;
      currentTitle: string | null;
      snapshotAuthorNote: string;
      currentAuthorNote: string;
    }
  /** 버전 뒤에 지워진 화(마지막 묶음 삭제). 내용이 남아 있지 않다. */
  | { kind: "deleted"; chapterId: string }
  /** 버전 뒤에 생긴 화. 되돌려도 그대로 남는다. */
  | { kind: "added"; chapterId: string; ordinal: number; title: string | null };

/**
 * 버전의 화 목록과 지금 화 목록을 맞춘다. 버전 쪽 순서(그때 화 순서)를 따르고, 버전 뒤에 생긴 화는 화 번호 순으로
 * 끝에 붙인다. 버전이 지워진 화라고 적었거나(`deleted`) 지금 상세에 없는 화는 지워진 화다 — 서버는 마지막 묶음을
 * 지울 때 버전 안 그 화 항목도 함께 지운다.
 *
 * 작가의 말은 버전에 `null` 로 올 수 있어(옛 버전) 빈 글로 본다.
 */
export function toSnapshotChapterRows(
  snapshot: Pick<NovelSnapshotDetail, "chapters">,
  chapters: readonly NovelChapterSummary[],
): SnapshotChapterRow[] {
  const byId = new Map(chapters.map((chapter) => [chapter.id, chapter]));
  const seen = new Set<string>();
  const rows: SnapshotChapterRow[] = snapshot.chapters.map((item) => {
    seen.add(item.chapterId);
    const current = byId.get(item.chapterId);
    if (item.deleted || current === undefined) return { kind: "deleted", chapterId: item.chapterId };
    const snapshotAuthorNote = item.authorNote ?? "";
    return {
      kind: "kept",
      chapterId: item.chapterId,
      ordinal: current.ordinal,
      isChanged:
        item.revisionId !== current.currentRevisionId ||
        item.title !== current.title ||
        snapshotAuthorNote !== current.authorNote,
      snapshotRevisionId: item.revisionId,
      currentRevisionId: current.currentRevisionId,
      snapshotTitle: item.title,
      currentTitle: current.title,
      snapshotAuthorNote,
      currentAuthorNote: current.authorNote,
    };
  });
  const added = chapters
    .filter((chapter) => !seen.has(chapter.id))
    .sort((a, b) => a.ordinal - b.ordinal)
    .map((chapter): SnapshotChapterRow => ({
      kind: "added",
      chapterId: chapter.id,
      ordinal: chapter.ordinal,
      title: chapter.title,
    }));
  return [...rows, ...added];
}

/** 소설 단위 칸 하나(제목·소개·설정 노트)의 버전 값과 지금 값. */
export type SnapshotFieldRow = { label: string; before: string; after: string; isChanged: boolean };

export function toSnapshotFieldRows(
  snapshot: Pick<NovelSnapshotDetail, "title" | "synopsis" | "settingNotes">,
  novel: Pick<NovelDetailResponse, "title" | "synopsis" | "settingNotes">,
): SnapshotFieldRow[] {
  const fields: [string, string, string][] = [
    ["소설 제목", snapshot.title ?? "", novel.title ?? ""],
    ["소개", snapshot.synopsis, novel.synopsis],
    ["설정 노트", snapshot.settingNotes, novel.settingNotes],
  ];
  return fields.map(([label, before, after]) => ({ label, before, after, isChanged: before !== after }));
}

/** 버전 때 인물 하나와 지금 그 인물의 카드. */
export type SnapshotCharacterRow = {
  snapshotCharacterId: string;
  /** 지금 이 인물을 보이는 이름 — 버전 뒤에 다른 카드로 합쳐졌으면 살아남은 카드의 이름이다. */
  currentName: string | undefined;
  snapshotName: string;
  /** 버전 뒤에 다른 카드로 합쳐졌나. */
  isMerged: boolean;
  beforeMemo: string;
  afterMemo: string;
  isChanged: boolean;
};

/**
 * 버전 때 인물 카드를 지금 카드와 맞춘다. 같은 카드가 있으면 그 카드, 없으면 그 이름을 별칭으로 가진 카드(버전 뒤
 * 합치기로 흡수된 경우 — 흡수된 이름은 남는 카드의 별칭이 된다)와 맞춘다. 되돌리기도 같은 규칙으로 살아남은 카드에
 * 메모를 되돌린다. 어느 쪽도 없으면 지금 카드가 없는 인물이다.
 */
export function toSnapshotCharacterRows(
  snapshot: Pick<NovelSnapshotDetail, "characters">,
  characters: readonly Pick<NovelCharacterResponse, "id" | "name" | "aliases" | "memo">[],
): SnapshotCharacterRow[] {
  return snapshot.characters.map((item) => {
    const same = characters.find((character) => character.id === item.id);
    const survivor = same ?? characters.find((character) => character.aliases.includes(item.name));
    const afterMemo = survivor?.memo ?? "";
    return {
      snapshotCharacterId: item.id,
      currentName: survivor?.name,
      snapshotName: item.name,
      isMerged: same === undefined && survivor !== undefined,
      beforeMemo: item.memo,
      afterMemo,
      isChanged: survivor === undefined || item.memo !== afterMemo || (same !== undefined && same.name !== item.name),
    };
  });
}

/**
 * 되돌리기가 건너뛴 화의 안내. 화가 지워졌거나 그때 판이 지워진 화를 서버가 건너뛴다. 지금 목차에 있는 화는 번호로
 * 말하고(그때 글이 없어 못 되돌렸다), 목차에 없는 화는 수만 센다(지워진 화라 번호가 남아 있지 않다). 건너뛴 화가 없으면
 * `undefined`.
 */
export function toSkippedChaptersNotice(
  skippedChapterIds: readonly string[],
  chapters: readonly Pick<NovelChapterSummary, "id" | "ordinal">[],
): string | undefined {
  if (skippedChapterIds.length === 0) return undefined;
  const ordinalById = new Map(chapters.map((chapter) => [chapter.id, chapter.ordinal]));
  const ordinals = skippedChapterIds
    .map((id) => ordinalById.get(id))
    .filter((ordinal) => ordinal !== undefined)
    .sort((a, b) => a - b);
  const goneCount = skippedChapterIds.length - ordinals.length;
  const parts: string[] = [];
  if (ordinals.length > 0) {
    parts.push(`${ordinals.map((ordinal) => `${ordinal}화`).join("·")}는 그때 글이 남아 있지 않아 되돌리지 못했어요.`);
  }
  if (goneCount > 0) parts.push(`지워진 화 ${goneCount}개는 되돌리지 못했어요.`);
  return parts.join(" ");
}
