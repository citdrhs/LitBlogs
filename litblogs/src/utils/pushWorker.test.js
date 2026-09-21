import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

const source = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../public/push-sw.js"), "utf8");
const origin = "https://school.example";
const worker = (base, windows = []) => {
  const listeners = {};
  const registration = { scope: `${origin}${base}`, showNotification: vi.fn().mockResolvedValue(undefined) };
  const clients = { matchAll: vi.fn().mockResolvedValue(windows), openWindow: vi.fn().mockResolvedValue(undefined) };
  vm.runInNewContext(source, { URL, self: { registration, addEventListener: (name, handler) => { listeners[name] = handler; } }, clients });
  const dispatch = async (name, event) => {
    let done;
    listeners[name]({ ...event, waitUntil: (promise) => { done = promise; } });
    await done;
  };
  return { clients, registration, dispatch };
};

describe.each(["/", "/dren/"])("push worker at %s", (base) => {
  it("scopes notification assets and canonical payload destinations", async () => {
    const instance = worker(base);
    await instance.dispatch("push", { data: { json: () => ({ url: "/class-feed/7" }) } });
    expect(instance.registration.showNotification).toHaveBeenCalledWith("LitBlogs Reminder", expect.objectContaining({
      icon: `${origin}${base}logo.png`, badge: `${origin}${base}logo.png`, data: { url: `${origin}${base}class-feed/7` },
    }));
  });

  it("opens only an in-scope window and awaits navigation before focus", async () => {
    const sibling = { url: `${origin}/other/`, navigate: vi.fn(), focus: vi.fn() };
    const own = { url: `${origin}${base}student-hub`, navigate: vi.fn().mockResolvedValue(undefined), focus: vi.fn() };
    const instance = worker(base, base === "/" ? [own] : [sibling, own]);
    await instance.dispatch("notificationclick", { notification: { close: vi.fn(), data: { url: `${origin}${base}class-feed/7` } } });
    expect(own.navigate).toHaveBeenCalledWith(`${origin}${base}class-feed/7`);
    expect(own.focus).toHaveBeenCalledOnce();
    expect(sibling.navigate).not.toHaveBeenCalled();
    expect(sibling.focus).not.toHaveBeenCalled();
  });

  it.each(["https://other.example/class-feed", "//other.example/class-feed", "/dren/../other/", "/dren/%2e%2e/other/"])("contains an unsafe destination %s", async (destination) => {
    const instance = worker(base);
    await instance.dispatch("notificationclick", { notification: { close: vi.fn(), data: { url: destination } } });
    expect(instance.clients.openWindow).toHaveBeenCalledWith(`${origin}${base}class-feed`);
  });
});

it("does not navigate a sibling window when no app window exists", async () => {
  const sibling = { url: `${origin}/dren-other/`, navigate: vi.fn(), focus: vi.fn() };
  const instance = worker("/dren/", [sibling]);
  await instance.dispatch("notificationclick", { notification: { close: vi.fn(), data: { url: "/class-feed" } } });
  expect(sibling.navigate).not.toHaveBeenCalled();
  expect(sibling.focus).not.toHaveBeenCalled();
  expect(instance.clients.openWindow).toHaveBeenCalledWith(`${origin}/dren/class-feed`);
});
