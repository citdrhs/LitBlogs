self.addEventListener('push', (event) => {
  let payload = {};

  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {
      title: 'Notification',
      body: event.data ? event.data.text() : 'You have a new update.',
    };
  }

  const title = payload.title || 'LitBlogs Reminder';
  const options = {
    body: payload.body || 'You have a new reminder.',
    icon: '/logo.png',
    badge: '/logo.png',
    tag: payload.tag || 'litblogs-notification',
    data: {
      url: payload.url || '/class-feed',
    },
    renotify: true,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const destination = (event.notification && event.notification.data && event.notification.data.url) || '/class-feed';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) {
          client.navigate(destination);
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(destination);
      }
      return undefined;
    })
  );
});
