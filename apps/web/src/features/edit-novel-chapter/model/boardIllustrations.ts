import type { NovelRevisionResponse } from "@/entities/novel";

import type { ParagraphRange } from "./paragraphRange";

/** 내 소설 화 응답의 삽화 한 장. `id` 는 그 판의 배치 id 라 판이 바뀌면 같은 그림도 id 가 바뀐다. 자리(`anchorBlockId`·
 * `placement`)가 비었으면 위치 확인 필요(앵커 문단을 잃은 그림)다. */
export type BoardIllustration = NovelRevisionResponse["illustrations"][number];

/** 보드가 삽화를 그리고 고르는 데 쓰는 판의 조각. 삽화 칸은 스위치가 꺼졌으면 비어 오고, API 를 삽화 칸 이전으로 되돌린
 * 동안에는 없다 — 둘 다 문단만인 지금 본문이다. */
export type BoardRevision = {
  id: string;
  blocks: readonly { id: string }[];
  illustrations?: readonly BoardIllustration[];
  unplacedIllustrations?: readonly BoardIllustration[];
};

export type IllustrationPlacement = "before" | "after";

/** 문단마다 앞·뒤 그림(자리 안 순서대로)과 위치 확인 필요 그림. `before[i]`·`after[i]` 는 문단 i 의 자리다. */
export type IllustrationSpots = {
  before: BoardIllustration[][];
  after: BoardIllustration[][];
  unplaced: BoardIllustration[];
};

/** 옮길 자리 — 지금 판의 블록 id 와 그 앞·뒤. 순서는 보내지 않는다(그 자리 맨 끝으로 간다). */
export type PlacementTarget = { anchorBlockId: string; placement: IllustrationPlacement };

/** 옮기기를 시작한 그림. 시작한 판을 함께 들어, 판이 바뀌면 저절로 끝난 것으로 읽는다(`toActiveMove`). */
export type MovingIllustration = { illustrationId: string; revisionId: string };

/** 그림이 어디서 왔는가 — 서버가 그 출처로 쓸 수 있는 그림인지 본다. 기기에서 올린 그림·내 생성 이미지·원작 그림. */
export type IllustrationSource = BoardIllustration["source"];

export type ParagraphAction =
  | "aiEdit"
  | "manualEdit"
  | "attach"
  | "clearSelection"
  | "placeBefore"
  | "placeAfter"
  | "cancelMove";
export type IllustrationAction = "move" | "replace" | "detach";

/** 한 화에 둘 수 있는 삽화 수. 서버의 상한과 같은 값이고, 서버처럼 위치 확인 필요인 그림도 센다. */
export const NOVEL_ILLUSTRATION_LIMIT = 10;

/** 붙이기가 실패한 요청에서 다시 넣기에 쓸 것 — 같은 그림(이미 올린 파일이면 다시 올리지 않는다)과 같은 자리. 기준 판은 들지
 * 않는다(`toRetryAttachRequest` 가 그때의 지금 판으로 채운다). */
export type FailedAttach = { assetId: string; source: IllustrationSource; target: PlacementTarget };

/** 붙이기 요청 하나. */
export type AttachRequest = FailedAttach & { baseRevisionId: string };

const byOrder = (a: BoardIllustration, b: BoardIllustration) => a.order - b.order;

/** 판의 삽화를 문단 자리로 편다. 앵커 블록이 그 판에 없는 그림은 읽기 화면처럼 빠진다 — 같은 판의 응답이라 생기지 않지만,
 * 생기면 화 전체를 깨는 대신 그 그림만 빠진다. */
export function toIllustrationSpots(revision: BoardRevision): IllustrationSpots {
  const indexById = new Map(revision.blocks.map((block, index) => [block.id, index]));
  const before: BoardIllustration[][] = revision.blocks.map(() => []);
  const after: BoardIllustration[][] = revision.blocks.map(() => []);
  for (const illustration of revision.illustrations ?? []) {
    const index = illustration.anchorBlockId === null ? undefined : indexById.get(illustration.anchorBlockId);
    if (index === undefined || illustration.placement === null) continue;
    (illustration.placement === "before" ? before : after)[index]?.push(illustration);
  }
  for (const spot of [...before, ...after]) spot.sort(byOrder);
  return { before, after, unplaced: [...(revision.unplacedIllustrations ?? [])].sort(byOrder) };
}

/** 고른 문단의 앞·뒤로 옮길 요청 자리. 보내도 바뀌는 것이 없으면 `null` 이다 — 그 자리 맨 끝에 이미 있는 그림을 같은
 * 자리로 보내면 서버는 같은 배치의 새 판을 하나 더 쌓는다(판 이력에 빈 판이 는다). 같은 자리라도 맨 끝이 아니면 순서가
 * 바뀌므로 보낸다. 지금 판에 없는 문단도 `null` 이다. */
export function toMoveTarget(
  revision: BoardRevision,
  illustration: BoardIllustration,
  paragraphIndex: number,
  placement: IllustrationPlacement,
): PlacementTarget | null {
  const anchorBlockId = revision.blocks[paragraphIndex]?.id;
  if (anchorBlockId === undefined) return null;
  if (illustration.anchorBlockId === anchorBlockId && illustration.placement === placement) {
    const spotSize = (revision.illustrations ?? []).filter(
      (item) => item.anchorBlockId === anchorBlockId && item.placement === placement,
    ).length;
    if (illustration.order >= spotSize - 1) return null;
  }
  return { anchorBlockId, placement };
}

/** 옮긴 뒤 새 판에서 옮긴 그림의 id — 그 자리 맨 끝의 그림이다(순서를 비워 보내 맨 끝으로 갔다). 없으면 `undefined`. */
export function toMovedIllustrationId(revision: BoardRevision, target: PlacementTarget): string | undefined {
  return (revision.illustrations ?? [])
    .filter((item) => item.anchorBlockId === target.anchorBlockId && item.placement === target.placement)
    .sort(byOrder)
    .at(-1)?.id;
}

/** 바꾼 뒤 새 판에서 바꾼 그림의 id — 바꾸기는 자리·순서를 그대로 두므로 같은 자리·같은 순서의 그림이다. 없으면 `undefined`. */
export function toReplacedIllustrationId(revision: BoardRevision, replaced: BoardIllustration): string | undefined {
  return (revision.illustrations ?? []).find(
    (item) =>
      item.anchorBlockId === replaced.anchorBlockId &&
      item.placement === replaced.placement &&
      item.order === replaced.order,
  )?.id;
}

/** 지금 옮기는 중인 그림. 스위치가 꺼졌거나, 시작한 뒤 판이 바뀌었거나(다른 곳의 수정·충돌 뒤 다시 받기), 그 판에 그림이
 * 없으면 옮기는 중이 아니다 — 옛 판을 기준으로 다시 보내 같은 충돌을 되풀이하지 않게 상태를 고치지 않고 이렇게 읽는다. */
export function toActiveMove({
  isIllustrationsOn,
  moving,
  revision,
}: {
  isIllustrationsOn: boolean;
  moving: MovingIllustration | null;
  revision: BoardRevision;
}): BoardIllustration | null {
  if (!isIllustrationsOn || moving === null || moving.revisionId !== revision.id) return null;
  return (
    [...(revision.illustrations ?? []), ...(revision.unplacedIllustrations ?? [])].find(
      (item) => item.id === moving.illustrationId,
    ) ?? null
  );
}

/** 고른 문단 아래 동작 줄의 버튼. 옮기는 중이면 놓을 자리 고르기이고, 아니면 지금 화면의 셋에 스위치가 켜졌을 때만 그림
 * 붙이기가 더해진다. */
export function toParagraphActions({
  isMoving,
  isIllustrationsOn,
}: {
  isMoving: boolean;
  isIllustrationsOn: boolean;
}): ParagraphAction[] {
  if (isMoving) return ["placeBefore", "placeAfter", "cancelMove"];
  return isIllustrationsOn ? ["aiEdit", "manualEdit", "attach", "clearSelection"] : ["aiEdit", "manualEdit", "clearSelection"];
}

/** 고른 범위에 그림을 붙일 자리. 뒤면 범위의 마지막 문단 뒤, 앞이면 범위의 첫 문단 앞이다 — 여러 문단을 고르고 앞을 고른
 * 작가는 범위 끝 문단 앞(범위 한가운데)이 아니라 범위 맨 앞을 기대한다. 지금 판에 없는 문단이면 `null`. */
export function toAttachTarget(
  revision: BoardRevision,
  range: ParagraphRange,
  placement: IllustrationPlacement,
): PlacementTarget | null {
  const anchorBlockId = revision.blocks[placement === "before" ? range.start : range.end]?.id;
  return anchorBlockId === undefined ? null : { anchorBlockId, placement };
}

/** 한 화의 삽화가 상한에 닿았는가. 위치 확인 필요인 그림도 센다 — 서버가 그렇게 세므로, 빼고 세면 붙이기가 열려 있다가
 * 409 로 끝난다. */
export function isIllustrationLimitReached(revision: BoardRevision): boolean {
  return (revision.illustrations?.length ?? 0) + (revision.unplacedIllustrations?.length ?? 0) >= NOVEL_ILLUSTRATION_LIMIT;
}

/** 실패한 붙이기를 지금 판에 다시 보낼 요청. 기준 판은 늘 지금 판이다 — 실패한 요청의 옛 기준 판으로 다시 보내면 충돌
 * 409 가 끝없이 되풀이된다. 그 문단이 지금 판에 없으면(다른 곳에서 지웠다) `null` 이라 문단을 다시 골라야 한다. */
export function toRetryAttachRequest(revision: BoardRevision, failed: FailedAttach): AttachRequest | null {
  if (!revision.blocks.some((block) => block.id === failed.target.anchorBlockId)) return null;
  return { ...failed, baseRevisionId: revision.id };
}

/** 문단 사이 그림 아래의 조작. 스위치가 켜지고 고치기 모드일 때만 있다. 운영자가 내린 그림은 독자에게 안내 상자로만 서고
 * 그대로는 이 화를 다시 공개할 수 없어 바꾸기·떼기만 둔다(옮겨도 공개할 수 없는 것은 그대로다). 원작 이용 제한은 풀릴 수
 * 있어 옮기기도 둔다. */
export function toIllustrationActions({
  isIllustrationsOn,
  isFixMode,
  illustration,
}: {
  isIllustrationsOn: boolean;
  isFixMode: boolean;
  illustration: BoardIllustration;
}): IllustrationAction[] {
  if (!isIllustrationsOn || !isFixMode) return [];
  return illustration.withheld === "taken_down" ? ["replace", "detach"] : ["move", "replace", "detach"];
}

/** 위치 확인 필요 목록을 보이는가. 고치기 모드와 상관없다 — 독자에게 빠진 그림이 있다는 경고라서다. */
export function isUnplacedListShown({
  isIllustrationsOn,
  revision,
}: {
  isIllustrationsOn: boolean;
  revision: BoardRevision;
}): boolean {
  return isIllustrationsOn && (revision.unplacedIllustrations?.length ?? 0) > 0;
}

/** 그림 묶음의 이름 — "3번째 문단 뒤 삽화", 같은 자리에 여럿이면 "… 삽화 2". 그림 아래 버튼 이름이 모두 같아 이 이름이
 * 어느 그림의 버튼인지 가른다. */
export function toIllustrationLabel({
  paragraphIndex,
  placement,
  rank,
  count,
}: {
  paragraphIndex: number;
  placement: IllustrationPlacement;
  rank: number;
  count: number;
}): string {
  const base = `${paragraphIndex + 1}번째 문단 ${placement === "before" ? "앞" : "뒤"} 삽화`;
  return count > 1 ? `${base} ${rank + 1}` : base;
}

/** 직접 고치는 범위 문단들의 앞·뒤 그림 수. 입력칸이 그 문단 자리를 대신하므로 그림도 입력칸 아래 한 줄로 접는다. */
export function countIllustrationsInRange(spots: IllustrationSpots, range: ParagraphRange): number {
  let count = 0;
  for (let index = range.start; index <= range.end; index += 1) {
    count += (spots.before[index]?.length ?? 0) + (spots.after[index]?.length ?? 0);
  }
  return count;
}
