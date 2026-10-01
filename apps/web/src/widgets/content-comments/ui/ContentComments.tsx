import { useSessionQuery } from "@/entities/session";
import { useCommentDrafts } from "@/features/work-comments";

import { ContentCommentsView } from "./ContentCommentsView";

export function ContentComments({ contentId, targetCommentId }: { contentId: string; targetCommentId?: string }) {
  const { data: me } = useSessionQuery();
  const draftState = useCommentDrafts(contentId, me?.id);
  return <ContentCommentsView key={contentId + ":" + draftState.scopeKey} contentId={contentId}
    targetCommentId={targetCommentId} viewerId={me?.id ?? "guest"} isLoggedIn={!!me} draftState={draftState} />;
}
