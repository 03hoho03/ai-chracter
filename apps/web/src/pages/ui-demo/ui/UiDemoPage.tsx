import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Heart } from "lucide-react";
import { toast } from "sonner";

export function UiDemoPage() {
  const [nickname, setNickname] = useState("");

  return (
    <main className="mx-auto flex max-w-lg flex-col gap-8 p-6">
      <header>
        <h1 className="text-lg font-semibold">packages/ui 데모</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Button · Dialog · Input · Select · Toast 프리미티브 확인용 화면입니다.
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          아래 size 매트릭스는 치수 회귀 확인용입니다(design-system-goal-prompt.md D-4/D-8).
        </p>
      </header>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Button</h2>
        <div className="flex flex-wrap gap-2">
          <Button>기본</Button>
          <Button variant="secondary">보조</Button>
          <Button variant="outline">아웃라인</Button>
          <Button variant="ghost">고스트</Button>
          <Button variant="destructive">삭제</Button>
          <Button variant="link">링크</Button>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Input</h2>
        <Input
          name="nickname"
          placeholder="닉네임을 입력하세요"
          value={nickname}
          onChange={(event) => setNickname(event.target.value)}
        />
      </section>

      <section className="flex flex-col items-start gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Select</h2>
        <Select defaultValue="story">
          <SelectTrigger>
            <SelectValue placeholder="콘텐츠 유형" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="story">스토리</SelectItem>
            <SelectItem value="character">캐릭터</SelectItem>
          </SelectContent>
        </Select>
      </section>

      <section className="flex flex-col items-start gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Dialog</h2>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline">다이얼로그 열기</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>발행 전 확인</DialogTitle>
              <DialogDescription>
                이 캐릭터를 지금 발행하시겠어요? 발행 후에도 언제든 수정할 수 있어요.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter showCloseButton>
              <Button>발행하기</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </section>

      <section className="flex flex-col items-start gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">Toast</h2>
        <Button
          variant="secondary"
          onClick={() => toast.success("저장되었습니다")}
        >
          토스트 띄우기
        </Button>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Button size
        </h2>
        <div className="flex flex-col gap-2">
          <span className="text-xs text-muted-foreground">variant=default</span>
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex flex-col items-center gap-1.5">
              <Button size="xs">버튼</Button>
              <span className="text-xs text-muted-foreground">xs · 24px</span>
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <Button size="sm">버튼</Button>
              <span className="text-xs text-muted-foreground">sm · 32px</span>
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <Button size="default">버튼</Button>
              <span className="text-xs text-muted-foreground">default · 36px</span>
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <Button size="lg">버튼</Button>
              <span className="text-xs text-muted-foreground">lg · 40px</span>
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-xs text-muted-foreground">variant=outline</span>
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex flex-col items-center gap-1.5">
              <Button size="xs" variant="outline">버튼</Button>
              <span className="text-xs text-muted-foreground">xs · 24px</span>
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <Button size="sm" variant="outline">버튼</Button>
              <span className="text-xs text-muted-foreground">sm · 32px</span>
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <Button size="default" variant="outline">버튼</Button>
              <span className="text-xs text-muted-foreground">default · 36px</span>
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <Button size="lg" variant="outline">버튼</Button>
              <span className="text-xs text-muted-foreground">lg · 40px</span>
            </div>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          아이콘 버튼 size
        </h2>
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col items-center gap-1.5">
            <Button size="icon-xs" variant="outline" aria-label="좋아요">
              <Heart />
            </Button>
            <span className="text-xs text-muted-foreground">icon-xs · 24px</span>
          </div>
          <div className="flex flex-col items-center gap-1.5">
            <Button size="icon-sm" variant="outline" aria-label="좋아요">
              <Heart />
            </Button>
            <span className="text-xs text-muted-foreground">icon-sm · 32px</span>
          </div>
          <div className="flex flex-col items-center gap-1.5">
            <Button size="icon" variant="outline" aria-label="좋아요">
              <Heart />
            </Button>
            <span className="text-xs text-muted-foreground">icon · 36px</span>
          </div>
          <div className="flex flex-col items-center gap-1.5">
            <Button size="icon-lg" variant="outline" aria-label="좋아요">
              <Heart />
            </Button>
            <span className="text-xs text-muted-foreground">icon-lg · 40px</span>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Toggle size
        </h2>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-muted-foreground">sm · 32px</span>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              defaultValue="b"
              aria-label="Toggle sm 데모"
            >
              <ToggleGroupItem value="a">A</ToggleGroupItem>
              <ToggleGroupItem value="b">B</ToggleGroupItem>
              <ToggleGroupItem value="c">C</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-muted-foreground">default · 36px</span>
            <ToggleGroup
              type="single"
              variant="outline"
              defaultValue="b"
              aria-label="Toggle default 데모"
            >
              <ToggleGroupItem value="a">A</ToggleGroupItem>
              <ToggleGroupItem value="b">B</ToggleGroupItem>
              <ToggleGroupItem value="c">C</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-muted-foreground">lg · 40px</span>
            <ToggleGroup
              type="single"
              variant="outline"
              size="lg"
              defaultValue="b"
              aria-label="Toggle lg 데모"
            >
              <ToggleGroupItem value="a">A</ToggleGroupItem>
              <ToggleGroupItem value="b">B</ToggleGroupItem>
              <ToggleGroupItem value="c">C</ToggleGroupItem>
            </ToggleGroup>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          컨트롤 정렬 확인 (Input · SelectTrigger · Button)
        </h2>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-muted-foreground">
              sm 줄 (Input엔 sm 사이즈가 없어 36px 그대로)
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <Input placeholder="Input" className="w-40" />
              <Select defaultValue="story">
                <SelectTrigger size="sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="story">스토리</SelectItem>
                  <SelectItem value="character">캐릭터</SelectItem>
                </SelectContent>
              </Select>
              <Button size="sm">버튼</Button>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-xs text-muted-foreground">
              default 줄 (셋 다 36px)
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <Input placeholder="Input" className="w-40" />
              <Select defaultValue="story">
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="story">스토리</SelectItem>
                  <SelectItem value="character">캐릭터</SelectItem>
                </SelectContent>
              </Select>
              <Button>버튼</Button>
            </div>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          타이포 사다리
        </h2>
        <div className="flex flex-wrap items-baseline gap-4">
          <span className="text-badge">text-badge · 12px</span>
          <span className="text-xs">text-xs · 14px</span>
          <span className="text-sm">text-sm · 16px</span>
          <span className="text-lg">text-lg · 18px</span>
          <span className="text-xl">text-xl · 20px</span>
          <span className="text-2xl">text-2xl · 24px</span>
        </div>
      </section>
    </main>
  );
}
