export type ChainProgress = { completed: number; planned: number };

/** 연쇄(남은 대화 한 번에) 부모 작업의 진행 — 만든 묶음 / 만들 묶음. 서버가 아직 묶음 수를 정하지 않았으면(`null`)
 * 없다. 진행 줄은 그때 묶음 수 없이 쓰고 있다는 것만 말한다. */
export function toChainProgress(
  job: { completedBatches: number | null; plannedBatches: number | null } | null | undefined,
): ChainProgress | undefined {
  if (job === null || job === undefined || job.completedBatches === null || job.plannedBatches === null) return undefined;
  return { completed: job.completedBatches, planned: job.plannedBatches };
}

/** 진행 줄의 연쇄 문장. */
export function toChainRunningText(progress: ChainProgress | undefined): string {
  if (progress === undefined) return "남은 대화를 소설로 쓰고 있어요.";
  return `남은 대화를 소설로 쓰고 있어요 · 묶음 ${progress.completed}/${progress.planned}.`;
}
