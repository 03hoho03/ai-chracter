import { Button } from "@ai-character-chat/ui/components/button";

import { useCommentPreferencesQuery } from "@/entities/comment";

import { CommentNotificationPreferenceForm } from "./CommentNotificationPreferenceForm";
import { CommentMutedUsers } from "./CommentMutedUsers";

export function CommentSettings({ viewerId }: { viewerId: string }) {
  const query = useCommentPreferencesQuery(viewerId, true);
  return <section className="flex flex-col gap-4">
    <h2 className="text-xl font-semibold tracking-tight text-foreground">댓글 알림과 개인 보호</h2>
    <p className="break-keep text-sm text-muted-foreground">댓글 알림을 종류별로 설정하고 숨긴 사용자를 관리해요. 운영 안내는 계속 받아요.</p>
    <CommentPreferencesContent viewerId={viewerId} query={query} />
    <CommentMutedUsers viewerId={viewerId} />
  </section>;
}


function CommentPreferencesContent({ viewerId, query }: { viewerId: string; query: ReturnType<typeof useCommentPreferencesQuery> }) {
  if (query.isPending) return <p role="status" className="text-sm text-muted-foreground">댓글 설정을 불러오는 중…</p>;
  if (query.isError && !query.data) return <div><p role="alert" className="text-sm text-destructive-text">댓글 설정을 불러오지 못했어요.</p>
    <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>다시 시도</Button></div>;
  if (!query.data) return null;
  return <>
    {query.isError && <div><p role="alert" className="text-sm text-destructive-text">댓글 설정을 새로 불러오지 못했어요. 현재 입력은 유지돼요.</p>
      <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>다시 시도</Button></div>}
    <CommentNotificationPreferenceForm key={viewerId} viewerId={viewerId} preferences={query.data} />
  </>;
}
