export function findCommentMentionToken(body: string, caret: number) {
  const prefix = body.slice(0, caret);
  const match = prefix.match(/(?:^|\s)@([^\s@]{0,40})$/u);
  if (!match) return undefined;
  const q = match[1] ?? "";
  return { q, start: caret - q.length - 1, end: caret };
}
