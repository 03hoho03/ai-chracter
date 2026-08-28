import { Ban, EyeOff, Trash2 } from "lucide-react";

import type { ContentAccessStatus } from "@/entities/content";

type UnavailableReason = "restricted" | "deleted" | "private";

function resolveUnavailableReason(access: ContentAccessStatus): UnavailableReason {
  if (access.kind === "restricted") return "restricted";
  if (access.kind === "deleted") return "deleted";
  return "private"; // canViewDetailPage가 false인 나머지 경우: accessible + private + 비소유자
}

const COPY: Record<UnavailableReason, { icon: typeof Ban; title: string; description: string }> = {
  restricted: {
    icon: Ban,
    title: "이용이 제한된 콘텐츠예요",
    description: "운영 정책 위반으로 이용이 제한되어 더 이상 볼 수 없어요.",
  },
  deleted: {
    icon: Trash2,
    title: "삭제된 콘텐츠예요",
    description: "제작자 또는 운영팀에 의해 삭제되어 더 이상 볼 수 없어요.",
  },
  private: {
    icon: EyeOff,
    title: "비공개 콘텐츠예요",
    description: "제작자만 열람할 수 있도록 설정된 콘텐츠예요.",
  },
};

/** techspec-content-detail.md §2, §7 — canViewDetailPage가 false일 때 대신 노출하는 안내. */
export function ContentUnavailableState({ access }: { access: ContentAccessStatus }) {
  const reason = resolveUnavailableReason(access);
  const { icon: Icon, title, description } = COPY[reason];

  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <Icon aria-hidden className="size-8 text-muted-foreground" />
      <p className="text-base font-semibold text-foreground">{title}</p>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  );
}
