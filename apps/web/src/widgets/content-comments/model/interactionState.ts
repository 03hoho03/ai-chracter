export type ThreadExpansionOverride = { anchor?: string; isExpanded: boolean };
export type SavedTargetOverride = { sourceTargetId?: string; commentId: string };

export function resolveThreadExpanded(override: ThreadExpansionOverride | undefined, anchor: string | undefined, hasLocatedReplies: boolean): boolean {
  return override && override.anchor === anchor ? override.isExpanded : hasLocatedReplies;
}

export function resolveSavedTarget(override: SavedTargetOverride | undefined, sourceTargetId: string | undefined): string | undefined {
  return override?.sourceTargetId === sourceTargetId ? override?.commentId ?? sourceTargetId : sourceTargetId;
}
