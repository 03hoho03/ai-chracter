import { useState, type ReactNode } from "react";

import { CommentRow, type Comment } from "@/entities/comment";

type CommentReplyRowProps = {
  comment: Comment; isInheritedRevealed: boolean; isHighlighted: boolean; renderControls: (isRevealed: boolean) => ReactNode; editor: ReactNode;
};

export function CommentReplyRow({ comment, isInheritedRevealed, isHighlighted, renderControls, editor }: CommentReplyRowProps) {
  const [revealedVersion, setRevealedVersion] = useState<string>();
  const version = comment.updatedAt + ":" + comment.effectiveSpoiler;
  const isRevealed = !comment.effectiveSpoiler || revealedVersion === version ||
    (isInheritedRevealed && comment.inheritedSpoiler && !comment.isSpoiler);
  return <CommentRow comment={comment} isRevealed={isRevealed} onReveal={() => setRevealedVersion(version)}
    isHighlighted={isHighlighted} editor={editor}>{renderControls(isRevealed)}</CommentRow>;
}
