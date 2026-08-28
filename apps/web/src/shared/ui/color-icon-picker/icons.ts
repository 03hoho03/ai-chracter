import {
  Brain,
  Coins,
  Droplet,
  Flame,
  Heart,
  Moon,
  Shield,
  Smile,
  Sparkles,
  Star,
  Swords,
  Zap,
  type LucideIcon,
} from "lucide-react";

export type IconPickerOption = {
  name: string;
  label: string;
  Icon: LucideIcon;
}

/** lucide-react 아이콘 서브셋(techspec-builder-story.md §1.2) — 스탯에서 흔히 쓰는 개념 위주로 고정한다. */
export const ICON_OPTIONS: IconPickerOption[] = [
  { name: "Heart", label: "체력", Icon: Heart },
  { name: "Zap", label: "에너지", Icon: Zap },
  { name: "Brain", label: "정신력", Icon: Brain },
  { name: "Shield", label: "방어", Icon: Shield },
  { name: "Swords", label: "전투력", Icon: Swords },
  { name: "Star", label: "호감/명성", Icon: Star },
  { name: "Smile", label: "기분", Icon: Smile },
  { name: "Flame", label: "열정/분노", Icon: Flame },
  { name: "Droplet", label: "유대", Icon: Droplet },
  { name: "Moon", label: "피로", Icon: Moon },
  { name: "Coins", label: "재화", Icon: Coins },
  { name: "Sparkles", label: "마력", Icon: Sparkles },
];

/** 저장된 아이콘 이름(`ICON_OPTIONS[].name`)을 실제 컴포넌트로 되돌린다 — 스탯의 `icon`은
 * 그냥 문자열이라 그대로 렌더하면 화면에 "Droplet"이라는 글자가 나온다. 목록에 없는
 * 이름이면 `undefined`이고, 그때 무엇을 보여줄지는 호출부가 정한다(피커는 HelpCircle로
 * "고르라"고 알리지만, 읽기 전용 표시에서는 아무것도 안 그리는 편이 조용하다). */
export function getIconByName(name: string): LucideIcon | undefined {
  return ICON_OPTIONS.find((option) => option.name === name)?.Icon;
}
