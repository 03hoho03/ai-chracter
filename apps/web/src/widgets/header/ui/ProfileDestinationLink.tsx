import { Link } from "@tanstack/react-router";
import {
  BookText,
  FileText,
  House,
  IdCard,
  ImagePlus,
  Info,
  LayoutGrid,
  LifeBuoy,
  Megaphone,
  MessagesSquare,
  Plus,
  ReceiptText,
  ScrollText,
  Settings2,
  Shield,
  Sprout,
  Star,
  User,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { CloverIcon } from "@/entities/clover";
import type { MeResponse } from "@/entities/session";
import { SUPPORT_DESTINATIONS, type SupportDestinationKey } from "@/shared/config/supportDestinations";
import { assertNever } from "@/shared/lib/assertNever";

import type { ProfileDestinationKey } from "../model/profileDestinations";

/** 메뉴에 나오는 고객센터 목적지. `SUPPORT_DESTINATIONS`에는 푸터에만 걸리는 목적지(클로버 상품 안내)와
 * 크리에이터 정산 화면에서만 거는 목적지(크리에이터 정산 정책)도 있어
 * 그 전체가 아니라 그룹 배열에 든 키로 좁힌다 — 전체로 두면 메뉴에 없는 목적지에도 쓰이지 않을 아이콘을 요구한다. */
type MenuSupportDestinationKey = Extract<ProfileDestinationKey, SupportDestinationKey>;

/** 고객센터 목적지의 라벨·경로는 푸터와 함께 쓰는 `SUPPORT_DESTINATIONS`에서 오고, 아이콘만 헤더가 정한다. */
const SUPPORT_DESTINATION_ICON: Record<MenuSupportDestinationKey, LucideIcon> = {
  about: Info,
  notices: Megaphone,
  "inquiry-new": LifeBuoy,
  terms: FileText,
  privacy: Shield,
  "operation-policy": ScrollText,
  "youth-policy": Sprout,
  "refund-policy": ReceiptText,
};

/** 목적지 이름. 링크 글자이자, 글자를 숨기는 좌측 패널 레일의 툴팁 글자다 — 둘이 같은 소스를 읽어야 툴팁과 접근 이름이
 * 갈리지 않는다. 고객센터 목적지는 푸터와 함께 쓰는 `SUPPORT_DESTINATIONS` 의 라벨이다.
 *
 * - 내 소설·크리에이터 정산·대화 프로필·클로버는 페이지 h1 과 같은 문자열이다(`설정` 선례). 내 소설·정산은 허용된 계정에만
 *   보인다(`isProfileDestinationVisible`). */
export const PROFILE_DESTINATION_LABEL: Record<ProfileDestinationKey, string> = {
  home: "홈",
  builder: "작품 만들기",
  "my-works": "내 작품",
  novels: "내 소설",
  "studio-images": "이미지 생성",
  favorites: "즐겨찾기",
  chats: "내 채팅목록",
  profile: "내 프로필",
  personas: "대화 프로필",
  clover: "클로버",
  "creator-payout": "크리에이터 정산",
  mypage: "설정",
  about: SUPPORT_DESTINATIONS.about.label,
  notices: SUPPORT_DESTINATIONS.notices.label,
  "inquiry-new": SUPPORT_DESTINATIONS["inquiry-new"].label,
  terms: SUPPORT_DESTINATIONS.terms.label,
  privacy: SUPPORT_DESTINATIONS.privacy.label,
  "operation-policy": SUPPORT_DESTINATIONS["operation-policy"].label,
  "youth-policy": SUPPORT_DESTINATIONS["youth-policy"].label,
  "refund-policy": SUPPORT_DESTINATIONS["refund-policy"].label,
};

/** `me`는 `내 프로필`만 쓴다. 그 키에서만 필수로 두어, 비로그인 드로어가 공개 목적지를 `me` 없이 그릴 수 있게 한다. */
type ProfileDestinationLinkProps = ComponentPropsWithoutRef<"a"> &
  (
    | { destinationKey: "profile"; me: MeResponse }
    | { destinationKey: Exclude<ProfileDestinationKey, "profile">; me?: MeResponse }
  );

/** 라우트별 `to`/`params` 타입이 제각각이라(`/profile/$userId`만 params가 필요하다) 하나의 배열에
 * `to` 문자열을 담아 범용으로 렌더하면 라우터 제네릭과 계속 부딪힌다 — `switch`로 각 케이스를 그대로
 * 적어 리터럴 타입 추론을 그대로 받는다. `className`은 호출부가 준다 — `ProfileMenu`는 `DropdownMenuItem
 * asChild`의 기본 클래스에 얹혀야 해서 비워 두고(원래도 그랬다), 드로어는 자기 행 스타일을 준다.
 *
 * `forwardRef` + `...rest` 전달이 필수다 — 두 호출부 모두 `asChild`(`DropdownMenuItem`·`SheetClose`)로
 * 이 컴포넌트를 감싸는데, Radix의 Slot은 `ref`와 `onClick`(메뉴 선택·시트 닫기를 거는 바로 그 핸들러)을
 * 바로 아래 자식에 병합해 얹는다. 이 컴포넌트가 일반 함수 컴포넌트로 `className`만 받고 나머지를 버리면
 * 그 `onClick`이 실제 `<Link>`까지 못 가 "눌러도 메뉴/시트가 안 닫힌다"가 조용히 재현된다(실측). */
export const ProfileDestinationLink = forwardRef<HTMLAnchorElement, ProfileDestinationLinkProps>(function ProfileDestinationLink(
  { destinationKey, me, className, ...rest },
  ref,
) {
  const label = PROFILE_DESTINATION_LABEL[destinationKey];

  switch (destinationKey) {
    case "home":
      // 패널 내비의 홈이다. 로고도 홈으로 가지만 둘은 다르게 읽힌다 — 이 행은 이름 "홈"으로 읽히고 홈에 있을 때
      // 패널이 내비 행의 현재 위치 표시(채움·막대)를 그리도록 두는데, 로고는 "또나"로 읽히고 보이는 현재 위치 표시가
      // 없다. 로고를 누르면 홈으로 간다는 관습을 모르는 사람도 내비 목록에서 홈을 찾고 지금 홈에 있는지 알 수 있도록
      // 둘 다 둔다.
      return (
        <Link ref={ref} to="/" className={className} {...rest}>
          <House aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "builder":
      return (
        <Link ref={ref} to="/builder" className={className} {...rest}>
          <Plus aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "my-works":
      return (
        <Link ref={ref} to="/my" className={className} {...rest}>
          <LayoutGrid aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "studio-images":
      return (
        <Link ref={ref} to="/studio/images" className={className} {...rest}>
          <ImagePlus aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "creator-payout":
      return (
        <Link ref={ref} to="/creator-payout" className={className} {...rest}>
          <Wallet aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "chats":
      return (
        <Link ref={ref} to="/chats" className={className} {...rest}>
          <MessagesSquare aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "novels":
      // 글리프는 채팅 더보기의 `소설로 보기`와 같다.
      return (
        <Link ref={ref} to="/novels" className={className} {...rest}>
          <BookText aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "favorites":
      return (
        <Link ref={ref} to="/favorites" className={className} {...rest}>
          <Star aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "profile":
      return (
        <Link ref={ref} to="/profile/$userId" params={{ userId: me.id }} className={className} {...rest}>
          <User aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "personas":
      return (
        <Link ref={ref} to="/personas" className={className} {...rest}>
          <IdCard aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "clover":
      // 크기는 여기서 정한다 — 메뉴 항목·버튼의 svg
      // 크기 규칙은 `size-` 클래스가 이미 있는 svg 를 건너뛰므로, 기본 `size-3.5` 를 그대로 두면 이웃
      // 아이콘(16px)보다 작은 14px 로 그려진다.
      return (
        <Link ref={ref} to="/clover" className={className} {...rest}>
          <CloverIcon className="size-4" />
          <span>{label}</span>
        </Link>
      );
    case "mypage":
      return (
        <Link ref={ref} to="/mypage" className={className} {...rest}>
          <Settings2 aria-hidden />
          <span>{label}</span>
        </Link>
      );
    case "about":
    case "notices":
    case "inquiry-new":
    case "terms":
    case "privacy":
    case "operation-policy":
    case "youth-policy":
    case "refund-policy": {
      const { to } = SUPPORT_DESTINATIONS[destinationKey];
      const Icon = SUPPORT_DESTINATION_ICON[destinationKey];
      return (
        <Link ref={ref} to={to} className={className} {...rest}>
          <Icon aria-hidden />
          <span>{label}</span>
        </Link>
      );
    }
    default:
      // default 가 없으면 키를 목적지 배열(`profileDestinations.ts`)에만 추가하고 케이스를 빠뜨려도
      // typecheck 가 통과해 undefined 가 렌더되고, 빈 항목이 조용히 나타나 클릭해도 아무 일도
      // 안 난다(2026-09-15 적대적 리뷰가 실증). assertNever 로 다음 키 추가 때 컴파일 에러로 막는다.
      return assertNever(destinationKey);
  }
});
