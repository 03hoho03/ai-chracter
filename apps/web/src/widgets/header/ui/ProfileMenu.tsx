import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Link, useNavigate } from "@tanstack/react-router";
import { LogOut, MessagesSquare, Settings2, Star, User } from "lucide-react";
import { toast } from "sonner";

import type { MeResponse } from "../../../entities/session";
import { useLogoutMutation } from "../../../features/logout";

export function ProfileMenu({ me }: { me: MeResponse }) {
  const navigate = useNavigate();
  const logout = useLogoutMutation();

  const handleLogout = () => {
    logout.mutate(undefined, {
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
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label={`${me.nickname}님 계정 메뉴`}>
          <User aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="truncate">{me.nickname}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/chats">
            <MessagesSquare aria-hidden />
            내 채팅목록
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/favorites">
            <Star aria-hidden />
            즐겨찾기
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/profile/$userId" params={{ userId: me.id }}>
            <User aria-hidden />
            내 프로필
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/mypage">
            <Settings2 aria-hidden />
            마이페이지 · 설정
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" disabled={logout.isPending} onSelect={handleLogout}>
          <LogOut aria-hidden />
          로그아웃
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
