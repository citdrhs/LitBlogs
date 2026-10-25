import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DRAFT_SESSION_EXPIRED_EVENT,
  handleUnauthorizedResponse,
} from "./unauthorizedResponse.js";

const options = (overrides = {}) => ({
  clearAuth: vi.fn(),
  redirect: vi.fn(),
  signInPath: "/dren/sign-in",
  currentPath: "/dren/class-feed/1",
  eventTarget: new window.EventTarget(),
  ...overrides,
});

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("unauthorized browser responses", () => {
  it("exports the stable draft session event name", () => {
    expect(DRAFT_SESSION_EXPIRED_EVENT).toBe("litblogs:draft-session-expired");
  });

  it.each([undefined, 400, 403, 419, 500, "401"])("leaves status %s untouched", async (status) => {
    const error = { response: { status }, config: { url: "/posts", method: "post" } };
    const settings = options();
    const dispatch = vi.spyOn(settings.eventTarget, "dispatchEvent");

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(dispatch).not.toHaveBeenCalled();
    expect(settings.clearAuth).not.toHaveBeenCalled();
    expect(settings.redirect).not.toHaveBeenCalled();
  });

  it("preserves errors without a response", async () => {
    const error = new Error("synthetic network failure");
    const settings = options();
    const dispatch = vi.spyOn(settings.eventTarget, "dispatchEvent");

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(dispatch).not.toHaveBeenCalled();
    expect(settings.clearAuth).not.toHaveBeenCalled();
    expect(settings.redirect).not.toHaveBeenCalled();
  });

  it("clears auth before redirecting when no editor handles the 401", async () => {
    const error = { response: { status: 401 } };
    const settings = options();
    const callOrder = [];
    settings.clearAuth.mockImplementation(() => callOrder.push("clear"));
    settings.redirect.mockImplementation(() => callOrder.push("redirect"));
    settings.eventTarget.addEventListener(DRAFT_SESSION_EXPIRED_EVENT, (event) => {
      expect(event.cancelable).toBe(true);
      callOrder.push("event");
    });

    const rejected = handleUnauthorizedResponse(error, settings);

    expect(callOrder).toEqual(["event", "clear", "redirect"]);
    expect(settings.redirect).toHaveBeenCalledExactlyOnceWith("/dren/sign-in");
    await expect(rejected).rejects.toBe(error);
  });

  it("clears auth without looping a redirect when already on the sign-in page", async () => {
    const error = { response: { status: 401 } };
    const settings = options({ currentPath: "/dren/sign-in" });

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(settings.clearAuth).toHaveBeenCalledTimes(1);
    expect(settings.redirect).not.toHaveBeenCalled();
  });

  it("lets a synchronous cancelable editor listener preserve auth and the current page", async () => {
    const error = { response: { status: 401 } };
    const settings = options();
    let capturedEvent;
    settings.eventTarget.addEventListener(DRAFT_SESSION_EXPIRED_EVENT, (event) => {
      capturedEvent = event;
      event.preventDefault();
    });

    const rejected = handleUnauthorizedResponse(error, settings);

    expect(capturedEvent).toBeInstanceOf(window.Event);
    expect(capturedEvent.cancelable).toBe(true);
    expect(capturedEvent.defaultPrevented).toBe(true);
    expect(settings.clearAuth).not.toHaveBeenCalled();
    expect(settings.redirect).not.toHaveBeenCalled();
    await expect(rejected).rejects.toBe(error);
  });

  it("does not treat a listener's return value as cancellation", async () => {
    const error = { response: { status: 401 } };
    const settings = options();
    settings.eventTarget.addEventListener(DRAFT_SESSION_EXPIRED_EVENT, () => false);

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(settings.clearAuth).toHaveBeenCalledTimes(1);
    expect(settings.redirect).toHaveBeenCalledTimes(1);
  });

  it("bypasses global handling only for explicit draft reauthentication requests", async () => {
    const error = { response: { status: 401 }, config: { draftReauthentication: true } };
    const settings = options();
    const dispatch = vi.spyOn(settings.eventTarget, "dispatchEvent");

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(dispatch).not.toHaveBeenCalled();
    expect(settings.clearAuth).not.toHaveBeenCalled();
    expect(settings.redirect).not.toHaveBeenCalled();
  });

  it.each([false, "true", 1, undefined])("does not bypass handling for draftReauthentication=%s", async (value) => {
    const error = { response: { status: 401 }, config: { draftReauthentication: value } };
    const settings = options();

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(settings.clearAuth).toHaveBeenCalledTimes(1);
    expect(settings.redirect).toHaveBeenCalledTimes(1);
  });

  it("never retries a rejected publishing request or exposes its contents in the event", async () => {
    const adapter = vi.fn();
    const config = Object.freeze({
      url: "/posts", method: "post", data: "private unpublished student response", adapter,
    });
    const error = { response: { status: 401 }, config };
    const settings = options();
    const observed = [];
    settings.eventTarget.addEventListener(DRAFT_SESSION_EXPIRED_EVENT, (event) => {
      observed.push(event);
      event.preventDefault();
    });

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(error.config).toBe(config);
    expect(adapter).not.toHaveBeenCalled();
    expect(observed).toHaveLength(1);
    expect(observed[0].detail).toBeUndefined();
    expect(observed[0].config).toBeUndefined();
    expect(observed[0].error).toBeUndefined();
    expect(settings.clearAuth).not.toHaveBeenCalled();
    expect(settings.redirect).not.toHaveBeenCalled();
  });

  it("dispatches separate handled failures without replaying or redirecting either request", async () => {
    const settings = options();
    const listener = vi.fn((event) => event.preventDefault());
    settings.eventTarget.addEventListener(DRAFT_SESSION_EXPIRED_EVENT, listener);
    const errors = [{ response: { status: 401 } }, { response: { status: 401 } }];

    for (const error of errors) {
      await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);
    }

    expect(listener).toHaveBeenCalledTimes(2);
    expect(listener.mock.calls[0][0]).not.toBe(listener.mock.calls[1][0]);
    expect(settings.clearAuth).not.toHaveBeenCalled();
    expect(settings.redirect).not.toHaveBeenCalled();
  });

  it("uses the browser window by default", async () => {
    const error = { response: { status: 401 } };
    const settings = options({ eventTarget: undefined });
    const listener = vi.fn((event) => event.preventDefault());
    window.addEventListener(DRAFT_SESSION_EXPIRED_EVENT, listener, { once: true });

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(settings.clearAuth).not.toHaveBeenCalled();
    expect(settings.redirect).not.toHaveBeenCalled();
  });

  it("creates an event in the injected browser window's realm", async () => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const frameWindow = frame.contentWindow;
    const error = { response: { status: 401 } };
    const settings = options({ eventTarget: frameWindow });
    const listener = vi.fn((event) => {
      expect(event).toBeInstanceOf(frameWindow.Event);
      event.preventDefault();
    });
    frameWindow.addEventListener(DRAFT_SESSION_EXPIRED_EVENT, listener);

    await expect(handleUnauthorizedResponse(error, settings)).rejects.toBe(error);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(settings.clearAuth).not.toHaveBeenCalled();
    expect(settings.redirect).not.toHaveBeenCalled();
  });
});
