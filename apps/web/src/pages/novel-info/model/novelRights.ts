import { NOVEL_PERMISSION_COPY, type NovelPermission } from "@/entities/content";
import type { NovelDetailResponse } from "@/entities/novel";

/** 원작 상세(`GET /contents/{id}`)를 읽은 결과. 소설 상세에는 원작의 지금 허락이 없어 원작 상세에서 읽는다 — 그 응답은
 * 누가 보든 허락 단계를 싣고, 볼 수 없게 된 원작에도 200 이다. 못 읽었으면(원작 행 없음·일시 실패) `unavailable`.
 * `sourceAvailable` 은 원작이 운영 조치(이용제한·삭제)로 내려가지 않았는가다 — 비공개 전환은 내려간 것이 아니다. */
export type SourceRead =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "loaded"; novelPermission: NovelPermission; isOwner: boolean; sourceAvailable: boolean };

export type NovelRightsInput = {
  novel: Pick<
    NovelDetailResponse,
    "chatRoomId" | "writingLockedAt" | "writingLockPermission" | "serialLockedAt" | "serialLockPermission"
  >;
  source: SourceRead;
  /** 노벨 정책 스위치(가격 응답). 모르면(아직 못 받음) 꺼진 것으로 본다 — 켜졌을 때만 참인 문장을 보이지 않으려고. */
  policyV2Enabled: boolean | undefined;
};

/** 고정된 권리 한 줄. 잠겼으면 그 시각과 그때의 원작 허락, 그리고 이 소설에 지금 효력이 있으면 그 효력을 말한다. */
export type RightLine =
  | { kind: "none"; when: string }
  | { kind: "locked"; lockedAt: string; heldPermission: string; effect: string | undefined };

export type NovelRightsView = {
  /** 원작이 내 작품(`own`, 노벨에서는 원작자 공식)인가 남의 작품(`derived`, 파생)인가. 원작을 못 읽었으면 모른다. */
  origin: "own" | "derived" | undefined;
  /** 원래 대화방. 지워졌으면 null. */
  chatRoomId: string | null;
  allowance:
    | { kind: "loading" }
    | { kind: "unavailable" }
    | { kind: "sourceDown" }
    | { kind: "own" }
    | { kind: "permission"; permission: NovelPermission; label: string };
  writing: RightLine;
  serial: RightLine;
};

function toHeldPermission(permission: NovelPermission | null): string {
  // 허락 사본이 비어 있는 잠금은 뒤늦게 채웠거나 그 순간 원작 행이 없던 것이다 — 허락하지 않았다는 뜻이 아니다.
  return permission === null ? "그때 허락은 알 수 없어요" : `그때 허락 · ${NOVEL_PERMISSION_COPY[permission].label}`;
}

function toRightLine(
  lockedAt: string | null,
  permission: NovelPermission | null,
  when: string,
  effect: string | undefined,
): RightLine {
  if (lockedAt === null) return { kind: "none", when };
  return { kind: "locked", lockedAt, heldPermission: toHeldPermission(permission), effect };
}

/** 작품 정보의 "출처와 권리" 절이 그릴 것. 심사 상태는 여기 없다 — 바로 아래 "노벨 공개" 절이 말한다.
 *
 * 효력 문장은 남의 작품이 원작일 때만 붙는다 — 허락은 남에게 거는 조건이라 원작자 본인의 소설에는 거둘 허락이 없다.
 * 집필권은 첫 화 저장으로 잠기고 그 뒤로는 원작자가 허락을 거둬도 이어 쓴다(스위치 무관). 연재권은 노벨에 처음 공개될 때
 * 잠기지만, 허락을 거둬도 이어 공개하는 효력은 노벨 정책 스위치가 켜졌을 때뿐이다 — 꺼지면 잠금 사실만 남긴다. 효력이
 * 있어도 지금 그 일을 할 수 없으면(방이 지워져 새 화를 못 만듦, 원작이 운영 조치로 내려가 공개를 못 함) 문장을 뺀다. */
export function toNovelRightsView({ novel, source, policyV2Enabled }: NovelRightsInput): NovelRightsView {
  let origin: NovelRightsView["origin"];
  if (source.kind === "loaded") origin = source.isOwner ? "own" : "derived";
  const isDerived = origin === "derived";
  // 방이 지워진 소설은 이미 만든 화를 읽고 고칠 수만 있고 새 화를 만들 수 없다.
  const hasRoom = novel.chatRoomId !== null;
  const sourceUp = source.kind !== "loaded" || source.sourceAvailable;

  let allowance: NovelRightsView["allowance"];
  if (source.kind !== "loaded") allowance = { kind: source.kind };
  // 내려간 원작으로는 노벨에 새로 공개할 수 없어(연재권이 있어도), 원작자가 고른 단계를 "지금 허용"으로 보이면 거짓이 된다.
  else if (!source.sourceAvailable) allowance = { kind: "sourceDown" };
  else if (source.isOwner) allowance = { kind: "own" };
  else
    allowance = {
      kind: "permission",
      permission: source.novelPermission,
      label: NOVEL_PERMISSION_COPY[source.novelPermission].label,
    };

  return {
    origin,
    chatRoomId: novel.chatRoomId,
    allowance,
    writing: toRightLine(
      novel.writingLockedAt,
      novel.writingLockPermission,
      hasRoom ? "첫 화를 저장하면 생겨요." : "원래 대화가 지워져 새 화를 만들 수 없어요.",
      isDerived && hasRoom ? "원작자가 허락을 거둬도 이 소설은 이어 쓸 수 있어요." : undefined,
    ),
    serial: toRightLine(
      novel.serialLockedAt,
      novel.serialLockPermission,
      "노벨에 처음 공개되면 생겨요.",
      isDerived && sourceUp && policyV2Enabled === true ? "원작자가 허락을 거둬도 다음 화를 이어 공개할 수 있어요." : undefined,
    ),
  };
}
