import { Avatar, AvatarFallback, AvatarImage } from "@ai-character-chat/ui/components/avatar";

import type { ContentType } from "../../../entities/content";
import { useProfileQuery } from "../../../entities/profile";
import { useSessionQuery } from "../../../entities/session";
import { EditProfileDialog } from "../../../features/edit-profile";
import { ProfileContentSection } from "./ProfileContentSection";

function ProfileHeaderSkeleton() {
  return (
    <div className="flex items-center gap-4">
      <div className="size-20 shrink-0 animate-pulse rounded-full bg-muted" />
      <div className="flex flex-col gap-2">
        <div className="h-7 w-32 animate-pulse rounded bg-muted" />
        <div className="h-4 w-48 animate-pulse rounded bg-muted" />
      </div>
    </div>
  );
}

export function ProfilePage({
  userId,
  contentType,
  onContentTypeChange,
}: {
  userId: string;
  contentType: ContentType;
  onContentTypeChange: (type: ContentType) => void;
}) {
  const profileQuery = useProfileQuery(userId);
  const sessionQuery = useSessionQuery();
  const isOwner = sessionQuery.data?.id === userId;

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 px-6 py-10">
      {profileQuery.isPending && <ProfileHeaderSkeleton />}

      {profileQuery.isError && (
        <p className="text-sm text-destructive-text">
          {profileQuery.error.status === 404
            ? "존재하지 않거나 탈퇴한 사용자예요."
            : "프로필을 불러오지 못했어요. 잠시 후 다시 시도해주세요."}
        </p>
      )}

      {profileQuery.data && (
        <>
          <section className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-4">
              <Avatar className="size-20 shrink-0">
                <AvatarImage src={profileQuery.data.profileImageUrl ?? undefined} alt="" />
                <AvatarFallback className="text-2xl">{profileQuery.data.nickname.slice(0, 1)}</AvatarFallback>
              </Avatar>
              <div className="flex flex-col gap-1">
                <h1 className="text-2xl font-bold tracking-tight text-foreground">
                  {profileQuery.data.nickname}
                </h1>
                <p className="max-w-md text-sm text-muted-foreground">
                  {profileQuery.data.bio || "아직 소개글이 없어요."}
                </p>
              </div>
            </div>

            {isOwner && <EditProfileDialog userId={userId} profile={profileQuery.data} />}
          </section>

          <ProfileContentSection
            userId={userId}
            isOwner={isOwner}
            contentType={contentType}
            onContentTypeChange={onContentTypeChange}
          />
        </>
      )}
    </main>
  );
}
