import { Link } from "@tanstack/react-router";
import {
  ImagePlus,
  LayoutGrid,
  LifeBuoy,
  Megaphone,
  MessagesSquare,
  Plus,
  Settings2,
  Star,
  User,
} from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef } from "react";

import type { MeResponse } from "@/entities/session";
import { assertNever } from "@/shared/lib/assertNever";

/** MR-10 — 목적지는 이 배열 하나에서만 정한다. 좌측 드로어(`MobileNavDrawer`)가 같은 배열을 평면화해
 * 읽는다 — 두 곳이 각자 목록을 들면 한쪽에만 항목이 추가되는 게 이 저장소의 알려진 실패 모드다
 * (`toContentStatusTags` 선례: "같은 작품이 한 화면에서는 이용제한, 다른 화면에서는 공개가 됐다"). */
export type ProfileDestinationKey =
  | "builder"
  | "my-works"
  | "studio-images"
  | "chats"
  | "favorites"
  | "profile"
  | "mypage"
  | "notices"
  | "inquiry-new";

export const PROFILE_DESTINATION_GROUPS: readonly { label: string; keys: readonly ProfileDestinationKey[] }[] = [
  { label: "창작", keys: ["builder", "my-works", "studio-images"] },
  { label: "활동", keys: ["chats", "favorites"] },
  { label: "계정", keys: ["profile", "mypage"] },
  { label: "고객센터", keys: ["notices", "inquiry-new"] },
];

/** 라우트별 `to`/`params` 타입이 제각각이라(`/profile/$userId`만 params가 필요하다) 하나의 배열에
 * `to` 문자열을 담아 범용으로 렌더하면 라우터 제네릭과 계속 부딪힌다 — `switch`로 각 케이스를 그대로
 * 적어 리터럴 타입 추론을 그대로 받는다. `className`은 호출부가 준다 — `ProfileMenu`는 `DropdownMenuItem
 * asChild`의 기본 클래스에 얹혀야 해서 비워 두고(원래도 그랬다), 드로어는 자기 행 스타일을 준다.
 *
 * `forwardRef` + `...rest` 전달이 필수다 — 두 호출부 모두 `asChild`(`DropdownMenuItem`·`SheetClose`)로
 * 이 컴포넌트를 감싸는데, Radix의 Slot은 `ref`와 `onClick`(메뉴 선택·시트 닫기를 거는 바로 그 핸들러)을
 * 바로 아래 자식에 병합해 얹는다. 이 컴포넌트가 일반 함수 컴포넌트로 `className`만 받고 나머지를 버리면
 * 그 `onClick`이 실제 `<Link>`까지 못 가 "눌러도 메뉴/시트가 안 닫힌다"가 조용히 재현된다(실측). */
export const ProfileDestinationLink = forwardRef<
  HTMLAnchorElement,
  ComponentPropsWithoutRef<"a"> & { destinationKey: ProfileDestinationKey; me: MeResponse }
>(function ProfileDestinationLink({ destinationKey, me, className, ...rest }, ref) {
  switch (destinationKey) {
    case "builder":
      return (
        <Link ref={ref} to="/builder" className={className} {...rest}>
          <Plus aria-hidden />
          작품 만들기
        </Link>
      );
    case "my-works":
      return (
        <Link ref={ref} to="/my" className={className} {...rest}>
          <LayoutGrid aria-hidden />
          내 작품
        </Link>
      );
    case "studio-images":
      return (
        <Link ref={ref} to="/studio/images" className={className} {...rest}>
          <ImagePlus aria-hidden />
          이미지 생성
        </Link>
      );
    case "chats":
      return (
        <Link ref={ref} to="/chats" className={className} {...rest}>
          <MessagesSquare aria-hidden />
          내 채팅목록
        </Link>
      );
    case "favorites":
      return (
        <Link ref={ref} to="/favorites" className={className} {...rest}>
          <Star aria-hidden />
          즐겨찾기
        </Link>
      );
    case "profile":
      return (
        <Link ref={ref} to="/profile/$userId" params={{ userId: me.id }} className={className} {...rest}>
          <User aria-hidden />
          내 프로필
        </Link>
      );
    case "mypage":
      return (
        <Link ref={ref} to="/mypage" className={className} {...rest}>
          <Settings2 aria-hidden />
          설정
        </Link>
      );
    case "notices":
      return (
        <Link ref={ref} to="/notices" className={className} {...rest}>
          <Megaphone aria-hidden />
          공지사항
        </Link>
      );
    case "inquiry-new":
      return (
        <Link ref={ref} to="/inquiries/new" className={className} {...rest}>
          <LifeBuoy aria-hidden />
          문의하기
        </Link>
      );
    default:
      // MR-10 — default 가 없으면 키를 유니언·PROFILE_DESTINATION_GROUPS 배열에만 추가하고 케이스를
      // 빠뜨려도 typecheck 가 통과해 undefined 가 렌더되고, 빈 항목이 조용히 나타나 클릭해도 아무 일도
      // 안 난다(2026-09-15 적대적 리뷰가 실증). assertNever 로 다음 키 추가 때 컴파일 에러로 막는다.
      return assertNever(destinationKey);
  }
});
