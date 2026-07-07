/** techspec-home-discovery.md §2 — 홈 검색/필터와 즐겨찾기 목록이 공용으로 쓰는 결과 0건 안내. */
export function ContentListEmptyState({ message = "조건에 맞는 작품이 없어요." }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-16 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
