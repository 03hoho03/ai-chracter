const segmenter = new Intl.Segmenter("ko", { granularity: "grapheme" });

export function countCommentGraphemes(value: string): number {
  return [...segmenter.segment(value)].length;
}

/** Cursors can overlap when popularity or pinning changes while another page is loaded. */
export function uniqueComments<T extends { id: string }>(items: T[]): T[] {
  const result = new Map<string, T>();
  for (const item of items) result.set(item.id, item);
  return [...result.values()];
}
