import type { NovelBlockEditPatch, NovelPendingBlockEdit } from "@/entities/novel";

/** 적용·버리기 요청의 단위 — 묶음에 들지 않은 수정안 하나, 또는 묶음 하나. */
export type PatchUnitRequest = { patchId: string } | { bundleId: string };

/** 적용·버리기 단위 하나. 묶음이면 원소 전부를 함께 적용·버린다. */
export type PatchUnitView = {
  jobId: string;
  /** 화면 안에서 단위를 가리키는 열쇠(진행 중 표시용). */
  key: string;
  request: PatchUnitRequest;
  isBundle: boolean;
  patchIds: string[];
  /** 원소가 놓인 문단 인덱스(본문 차례). 블록이 지금 판에 없는 원소는 빠진다. */
  indexes: number[];
  /** 묶음의 까닭(서버가 적은 문장). 독립 수정안은 `null`. */
  reason: string | null;
  /** 원소가 모두 대기이고 지금 판에 쓸 수 있는가. 하나라도 아니면 적용하지 못하고 버리기만 된다. */
  isApplicable: boolean;
  /** 다시 검사로 남은 원소를 따로 적용해도 되는지 물을 수 있는가 — 묶음에 사용자가 고친 원소(지금 판에 그 문단이 있는)와 아직 쓸 수
   * 있는 원소가 함께 있을 때만이다. 서버도 그 밖에는 모델을 부르지 않고 409 로 거절한다. 독립 수정안은 늘 거짓이다. */
  canRecheck: boolean;
  /** 든 요청의 번호("요청 1"). 한 화에 요청이 하나면 없다. */
  jobLabel: string | undefined;
};

/** 블록 자리에 놓이는 수정안 하나. */
export type PatchCardView = {
  jobId: string;
  /** 든 요청의 번호("요청 1"). 한 화에 요청이 하나면 없다. */
  jobLabel: string | undefined;
  patch: NovelBlockEditPatch;
  index: number;
  isApplicable: boolean;
  /** 든 묶음. 묶음 원소에는 자기 적용·버리기가 없다. */
  bundleId: string | undefined;
  /** 묶음에 들지 않은 수정안의 단위 — 카드가 자기 적용·버리기를 단다. */
  unit: PatchUnitView | undefined;
};

/** 작업 하나의 꼬리 줄 — 요청 문장과 "남은 수정안 모두 버리기". 자리를 잃은 단위(블록이 지금 판에 없음)도 여기 모은다. */
export type PatchJobView = {
  jobId: string;
  /** 요청 번호("요청 1"). 한 화에 요청이 하나면 없다. */
  jobLabel: string | undefined;
  instruction: string;
  unplacedUnits: PatchUnitView[];
};

export type PatchLayout = {
  /** 문단 인덱스 → 그 블록 자리에 그 문단 대신 놓일 수정안들(작업 차례). */
  cardsAt: Map<number, PatchCardView[]>;
  /** 문단 인덱스 → 그 자리 뒤에 서는 묶음의 함께 적용·버리기(마지막 원소 뒤). */
  bundlesAfter: Map<number, PatchUnitView[]>;
  /** 문단 인덱스 → 그 자리 뒤에 서는 작업 꼬리 줄(그 작업의 마지막 수정안 뒤, 자리가 없으면 화 끝). */
  jobsAfter: Map<number, PatchJobView[]>;
  /** 수정안이 놓여 고르기 버튼이 아닌 문단. */
  cardBlockIndexes: Set<number>;
};

function isFresh(patch: NovelBlockEditPatch): boolean {
  return patch.state === "pending" && patch.fresh;
}

function push<T>(map: Map<number, T[]>, index: number, item: T) {
  const items = map.get(index);
  if (items === undefined) map.set(index, [item]);
  else items.push(item);
}

/** 한 화의 요청이 둘 이상이면 맡긴 차례(같은 시각이면 id 차례)로 "요청 n" 을 매긴다 — 두 요청의 수정안이 한 장면 안에서 엇갈리면
 * 꼬리 줄의 요청 문장만으로는 어느 카드가 어느 요청의 것인지 알 수 없다. 하나면 번호가 없다(지금과 같은 화면). */
function toJobLabels(edits: readonly NovelPendingBlockEdit[]): Map<string, string> {
  if (edits.length < 2) return new Map();
  // 시각은 문자열이 아니라 값으로 견준다 — 소수 초 자릿수가 다른 두 표기는 글자 차례와 시간 차례가 어긋날 수 있다.
  const ordered = [...edits].sort(
    (a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt) || a.id.localeCompare(b.id),
  );
  return new Map(ordered.map((edit, rank) => [edit.id, `요청 ${rank + 1}`]));
}

/** 상세의 여러 문단 수정 작업 → 본문 위 자리. 대기 수정안과, 버리기를 기다리는 쓸 수 없는 수정안만 그린다(적용·버린 것은 없다).
 *
 * - 독립 수정안: 대기든 서버가 낡음으로 바꿨든 그 블록 자리에 카드로 서고 자기 적용·버리기를 단다(쓸 수 없으면 버리기만).
 * - 묶음: 대기 원소가 하나라도 있을 때만 그린다. 원소는 각자 자리에 카드로 서고, 함께 적용·버리기는 마지막 원소 뒤에 한 번.
 * - 블록이 지금 판에 없으면 자리 대신 작업 꼬리 줄에서 센다. */
export function toPatchLayout(edits: readonly NovelPendingBlockEdit[], blockIds: readonly string[]): PatchLayout {
  const layout: PatchLayout = {
    cardsAt: new Map(),
    bundlesAfter: new Map(),
    jobsAfter: new Map(),
    cardBlockIndexes: new Set(),
  };
  const lastIndex = blockIds.length - 1;
  const jobLabels = toJobLabels(edits);
  for (const edit of edits) {
    const jobLabel = jobLabels.get(edit.id);
    const byId = new Map(edit.patches.map((patch) => [patch.id, patch]));
    const bundled = new Map<string, string>();
    for (const bundle of edit.bundles) for (const id of bundle.patchIds) bundled.set(id, bundle.id);
    const indexOf = (patch: NovelBlockEditPatch) => blockIds.indexOf(patch.blockId);
    const unplacedUnits: PatchUnitView[] = [];
    let jobLast = -1;

    const place = (unit: PatchUnitView, members: NovelBlockEditPatch[]) => {
      for (const patch of members) {
        const index = indexOf(patch);
        if (index < 0) continue;
        push(layout.cardsAt, index, {
          jobId: edit.id,
          jobLabel,
          patch,
          index,
          isApplicable: isFresh(patch),
          bundleId: unit.isBundle && "bundleId" in unit.request ? unit.request.bundleId : undefined,
          unit: unit.isBundle ? undefined : unit,
        });
        layout.cardBlockIndexes.add(index);
      }
      const last = unit.indexes.at(-1);
      if (last === undefined) {
        unplacedUnits.push(unit);
        return;
      }
      jobLast = Math.max(jobLast, last);
      if (unit.isBundle) push(layout.bundlesAfter, last, unit);
    };

    for (const bundle of edit.bundles) {
      const members = bundle.patchIds
        .map((id) => byId.get(id))
        .filter((patch): patch is NovelBlockEditPatch => patch !== undefined && (patch.state === "pending" || patch.state === "stale"));
      if (!members.some((patch) => patch.state === "pending")) continue;
      place(
        {
          jobId: edit.id,
          key: `${edit.id}:${bundle.id}`,
          request: { bundleId: bundle.id },
          isBundle: true,
          patchIds: members.map((patch) => patch.id),
          indexes: members.map(indexOf).filter((index) => index >= 0).sort((a, b) => a - b),
          reason: bundle.reason,
          isApplicable: members.every(isFresh),
          canRecheck: members.some((patch) => !isFresh(patch) && indexOf(patch) >= 0) && members.some(isFresh),
          jobLabel,
        },
        members,
      );
    }
    for (const patch of edit.patches) {
      if (bundled.has(patch.id) || (patch.state !== "pending" && patch.state !== "stale")) continue;
      const index = indexOf(patch);
      place(
        {
          jobId: edit.id,
          key: `${edit.id}:${patch.id}`,
          request: { patchId: patch.id },
          isBundle: false,
          patchIds: [patch.id],
          indexes: index < 0 ? [] : [index],
          reason: null,
          isApplicable: isFresh(patch),
          canRecheck: false,
          jobLabel,
        },
        [patch],
      );
    }
    push(layout.jobsAfter, jobLast < 0 ? lastIndex : jobLast, {
      jobId: edit.id,
      jobLabel,
      instruction: edit.instruction,
      unplacedUnits,
    });
  }
  return layout;
}

/** 작업의 지금 쓸 수 있는 대기 수정안 수. */
export function countFreshPatches(edit: NovelPendingBlockEdit): number {
  return edit.patches.filter(isFresh).length;
}

/** 그 블록들에 놓인 지금 쓸 수 있는 대기 수정안 수 — 직접 고치기 저장이 그 수정안을 쓸 수 없게 만드는지 미리 말할 때 쓴다. */
export function countFreshPatchesInBlocks(edits: readonly NovelPendingBlockEdit[], blockIds: ReadonlySet<string>): number {
  return edits.reduce((count, edit) => count + edit.patches.filter((patch) => isFresh(patch) && blockIds.has(patch.blockId)).length, 0);
}
