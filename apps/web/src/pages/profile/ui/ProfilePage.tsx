import { Avatar, AvatarFallback, AvatarImage } from "@ai-character-chat/ui/components/avatar";

import type { ContentType } from "@/entities/content";
import { useProfileQuery } from "@/entities/profile";
import { useSessionQuery } from "@/entities/session";
import { EditProfileDialog } from "@/features/edit-profile";

import { ProfileContentSection } from "./ProfileContentSection";

type ProfilePageProps = {
  userId: string;
  contentType: ContentType;
  onContentTypeChange: (type: ContentType) => void;
};

export function ProfilePage({
  userId,
  contentType,
  onContentTypeChange,
}: ProfilePageProps) {
  const profileQuery = useProfileQuery(userId);
  const sessionQuery = useSessionQuery();
  const isOwner = sessionQuery.data?.id === userId;

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 px-4 sm:px-6 py-10">
      <ProfileBody
        query={profileQuery}
        userId={userId}
        isOwner={isOwner}
        contentType={contentType}
        onContentTypeChange={onContentTypeChange}
      />
    </main>
  );
}

type ProfileBodyProps = {
  query: ReturnType<typeof useProfileQuery>;
  userId: string;
  isOwner: boolean;
  contentType: ContentType;
  onContentTypeChange: (type: ContentType) => void;
};

/** 로딩·에러·성공 세 갈래를 **early return 순서**로 강제한다(COMP-04). */
function ProfileBody({ query, userId, isOwner, contentType, onContentTypeChange }: ProfileBodyProps) {
  if (query.isPending) return <ProfileHeaderSkeleton />;

  if (query.isError) {
    return (
      <p className="text-sm text-destructive-text">
        {query.error.status === 404
          ? "존재하지 않거나 탈퇴한 사용자예요."
          : "프로필을 불러오지 못했어요. 잠시 후 다시 시도해주세요."}
      </p>
    );
  }

  const profile = query.data;
  if (!profile) return null;

  return (
    <>
      <section className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <Avatar className="size-20 shrink-0">
            <AvatarImage src={profile.profileImageUrl ?? undefined} alt="" />
            <AvatarFallback className="text-2xl">{profile.nickname.slice(0, 1)}</AvatarFallback>
          </Avatar>
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">{profile.nickname}</h1>
            <p className="max-w-md text-sm text-muted-foreground">{profile.bio || "아직 소개글이 없어요."}</p>
          </div>
        </div>

        {isOwner && <EditProfileDialog userId={userId} profile={profile} />}
      </section>

      <ProfileContentSection
        userId={userId}
        isOwner={isOwner}
        contentType={contentType}
        onContentTypeChange={onContentTypeChange}
      />
    </>
  );
}

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
