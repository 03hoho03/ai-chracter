type ComingSoonPageProps = {
  title: string;
  description: string;
}

/**
 * 헤더 프로필 드롭다운(US-033)이 가리키는 화면 중 아직 각자의 스토리로 구현되지 않은 목적지용 임시 페이지.
 * 해당 스토리가 완료되면 이 컴포넌트 대신 실제 화면으로 교체한다.
 */
export function ComingSoonPage({ title, description }: ComingSoonPageProps) {
  return (
    <main className="mx-auto flex min-h-[60vh] max-w-3xl flex-col items-center justify-center gap-2 px-6 text-center">
      <h1 className="text-lg font-semibold text-foreground">{title}</h1>
      <p className="text-sm text-muted-foreground">{description}</p>
    </main>
  );
}
