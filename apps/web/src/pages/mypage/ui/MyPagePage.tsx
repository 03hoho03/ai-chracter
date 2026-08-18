import type { DraftSummary } from "../../../entities/draft";
import { useDraftListQuery } from "../../../entities/draft";
import { ChangePasswordForm } from "../../../features/change-password";
import { useLogoutMutation } from "../../../features/logout";
import { WithdrawAccountDialog } from "../../../features/withdraw-account";
import type { Theme } from "../../../shared/model/theme";
import { themeAtom } from "../../../shared/model/theme";
import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Link, useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { BookOpen, Moon, Sun, UserRound } from "lucide-react";
import { toast } from "sonner";

const draftUpdatedAtFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const DRAFT_TYPE_LABEL: Record<DraftSummary["type"], string> = {
  character: "캐릭터",
  story: "스토리",
};

function DraftTypeIcon({ type }: { type: DraftSummary["type"] }) {
  return type === "character" ? <UserRound aria-hidden /> : <BookOpen aria-hidden />;
}

function DraftCard({ draft }: { draft: DraftSummary }) {
  return (
    <Link
      to="/builder/$type/$draftId"
      params={{ type: draft.type, draftId: draft.id }}
      className="flex gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:bg-muted"
    >
      <div className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted text-muted-foreground">
        {draft.thumbnailUrl ? (
          <img
            src={draft.thumbnailUrl}
            alt=""
            loading="lazy"
            decoding="async"
            className="size-full object-cover"
          />
        ) : (
          <DraftTypeIcon type={draft.type} />
        )}
      </div>
      <div className="flex min-w-0 flex-col justify-center gap-1">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <DraftTypeIcon type={draft.type} />
          {DRAFT_TYPE_LABEL[draft.type]}
        </div>
        <p className="truncate text-base font-semibold text-foreground">{draft.name}</p>
        <p className="text-xs text-muted-foreground">
          {draftUpdatedAtFormatter.format(new Date(draft.updatedAt))} 수정
        </p>
      </div>
    </Link>
  );
}

function DraftListSection() {
  const draftListQuery = useDraftListQuery();

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-2xl font-bold tracking-tight text-foreground">작성 중인 초안</h2>

      {draftListQuery.isPending && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {[0, 1].map((key) => (
            <div key={key} className="h-24 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      )}

      {draftListQuery.isError && (
        <p className="text-sm text-destructive">초안을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {draftListQuery.data && draftListQuery.data.length === 0 && (
        <p className="text-sm text-muted-foreground">아직 작성 중인 초안이 없어요.</p>
      )}

      {draftListQuery.data && draftListQuery.data.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {draftListQuery.data.map((draft) => (
            <DraftCard key={draft.id} draft={draft} />
          ))}
        </div>
      )}
    </section>
  );
}

function isTheme(value: string): value is Theme {
  return value === "dark" || value === "light";
}

function ThemeSection() {
  const [theme, setTheme] = useAtom(themeAtom);

  const handleValueChange = (value: string) => {
    // Radix ToggleGroup(type="single")은 이미 선택된 항목을 다시 누르면 빈 문자열을 emit한다 — 그 경우 무시해
    // 항상 정확히 하나만 선택된 상태를 유지한다.
    if (!isTheme(value)) return;
    setTheme(value);
  };

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-2xl font-bold tracking-tight text-foreground">테마</h2>
      <ToggleGroup
        type="single"
        variant="outline"
        value={theme}
        onValueChange={handleValueChange}
        aria-label="테마 선택"
      >
        <ToggleGroupItem value="dark">
          <Moon aria-hidden />
          다크
        </ToggleGroupItem>
        <ToggleGroupItem value="light">
          <Sun aria-hidden />
          라이트
        </ToggleGroupItem>
      </ToggleGroup>
    </section>
  );
}

function AccountSection() {
  const navigate = useNavigate();
  const logoutMutation = useLogoutMutation();

  const handleLogout = () => {
    logoutMutation.mutate(undefined, {
      onSuccess: () => {
        toast.success("로그아웃되었어요.");
        void navigate({ to: "/" });
      },
      onError: () => {
        toast.error("로그아웃에 실패했어요. 잠시 후 다시 시도해주세요.");
      },
    });
  };

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-2xl font-bold tracking-tight text-foreground">계정</h2>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={logoutMutation.isPending} onClick={handleLogout}>
          로그아웃
        </Button>
        <WithdrawAccountDialog />
      </div>
    </section>
  );
}

export function MyPagePage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-10 px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">마이페이지 · 설정</h1>

      <DraftListSection />

      <ThemeSection />

      <section className="flex flex-col gap-4">
        <h2 className="text-2xl font-bold tracking-tight text-foreground">비밀번호 변경</h2>
        <ChangePasswordForm />
      </section>

      <AccountSection />
    </main>
  );
}
