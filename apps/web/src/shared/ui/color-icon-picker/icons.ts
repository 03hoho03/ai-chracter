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

export interface IconPickerOption {
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
