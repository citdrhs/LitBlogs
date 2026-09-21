const appScope = new URL(self.registration.scope);
const defaultDestination = new URL('class-feed', appScope).href;

const isAppUrl = (url) => url.origin === appScope.origin
  && url.pathname.startsWith(appScope.pathname);

const notificationDestination = (value) => {
  if (typeof value !== 'string' || !value.trim()) return defaultDestination;
  const raw = value.trim();
  try {
    // Reject traversal before URL normalization can hide it.
    const decodedPath = decodeURIComponent(raw.split(/[?#]/, 1)[0]);
    if (/[\\\u0000-\u0020]/.test(raw) || /%2f|%5c/i.test(raw)
      || decodedPath.split('/').some((part) => part === '.' || part === '..')) {
      return defaultDestination;
    }
    // Existing server notifications store canonical class-feed paths.
    const candidate = /^\/class-feed(?:\/\d+)?(?:[?#]|$)/.test(raw)
      ? new URL(raw.slice(1), appScope)
      : new URL(raw, appScope);
    return isAppUrl(candidate) ? candidate.href : defaultDestination;
  } catch {
    return defaultDestination;
  }
};

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

  if (!payload || typeof payload !== 'object') payload = {};
  const title = payload.title || 'LitBlogs Reminder';
  const options = {
    body: payload.body || 'You have a new reminder.',
    icon: new URL('logo.png', appScope).href,
    badge: new URL('logo.png', appScope).href,
    tag: payload.tag || 'litblogs-notification',
    data: {
      url: notificationDestination(payload.url),
    },
    renotify: true,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const destination = notificationDestination(event.notification?.data?.url);

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (clientList) => {
      for (const client of clientList) {
        try {
          if (isAppUrl(new URL(client.url)) && typeof client.navigate === 'function'
            && typeof client.focus === 'function') {
            const navigated = await client.navigate(destination);
            return (navigated || client).focus();
          }
        } catch {
          // A closing app window must not redirect a sibling application's tab.
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(destination);
      }
      return undefined;
    })
  );
});
