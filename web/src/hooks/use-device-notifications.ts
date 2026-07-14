"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { NotificationOut } from "@/lib/api";
import { fetchNotifications, sendDormNotification } from "@/lib/api";
import { deviceKeys } from "@/lib/query-keys";

export function useDeviceNotifications(deviceId: string) {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: deviceKeys.notifications(deviceId),
    queryFn: () => fetchNotifications(deviceId),
  });
  const mutation = useMutation({
    mutationFn: ({ content, voiceBroadcast }: { content: string; voiceBroadcast: boolean }) =>
      sendDormNotification(deviceId, content, voiceBroadcast),
    onMutate: () => setError(""),
    onSuccess: (notification) => {
      queryClient.setQueryData<NotificationOut[]>(deviceKeys.notifications(deviceId), (current = []) => [
        notification,
        ...current.filter((item) => item.id !== notification.id),
      ]);
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "通知下发失败"),
  });

  return {
    notifications: query.data ?? [],
    notificationSending: mutation.isPending,
    error: error || (query.error instanceof Error ? query.error.message : ""),
    sendNotification: useCallback(
      (content: string, voiceBroadcast: boolean) => mutation.mutateAsync({ content, voiceBroadcast }),
      [mutation],
    ),
  };
}
