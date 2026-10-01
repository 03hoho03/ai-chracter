export const notificationKeys = {
  all: ["notification"] as const,
  viewer: (viewerId: string) => [...notificationKeys.all, viewerId] as const,
  list: (viewerId: string) => [...notificationKeys.viewer(viewerId), "list"] as const,
  unread: (viewerId: string) => [...notificationKeys.viewer(viewerId), "unread"] as const,
};
