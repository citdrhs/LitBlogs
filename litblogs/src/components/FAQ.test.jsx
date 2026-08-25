import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import FAQ from "./FAQ.jsx";

const TOPICS = [
  "How do I create a student account?",
  "How do I sign in?",
  "How can I join my teacher's class?",
  "How do I create, format, and publish a post?",
  "How do I add or remove images, videos, and PDFs?",
  "How do post drafts work?",
  "I forgot my password. How do I reset it?",
];

const renderFAQ = (props = {}) => render(
  <MemoryRouter>
    <FAQ darkMode={false} {...props} />
  </MemoryRouter>,
);

const controlledPanel = (trigger) => (
  document.getElementById(trigger.getAttribute("aria-controls"))
);

describe("FAQ student guide", () => {
  it("renders exactly seven student topics with concise numbered steps", () => {
    renderFAQ();

    const accordion = screen.getByRole("region", { name: "Student FAQ" });
    const triggers = within(accordion).getAllByRole("button");

    expect(triggers).toHaveLength(7);
    expect(triggers.map((trigger) => trigger.textContent.trim())).toEqual(TOPICS);

    triggers.forEach((trigger) => {
      fireEvent.click(trigger);
      expect(within(controlledPanel(trigger)).getByRole("list")).toBeInTheDocument();
    });
  });

  it("connects real accordion buttons to stable, uniquely labelled panels", () => {
    renderFAQ();

    const triggers = screen.getAllByRole("button");
    const triggerIds = new Set();
    const panelIds = new Set();

    triggers.forEach((trigger) => {
      const panelId = trigger.getAttribute("aria-controls");
      const panel = controlledPanel(trigger);

      expect(trigger).toHaveAttribute("type", "button");
      expect(trigger.id).toMatch(/^faq-trigger-[a-z0-9-]+$/);
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      expect(panelId).toMatch(/^faq-panel-[a-z0-9-]+$/);
      expect(panel).toHaveAttribute("role", "region");
      expect(panel).toHaveAttribute("aria-labelledby", trigger.id);
      expect(panel).toHaveAttribute("hidden");

      triggerIds.add(trigger.id);
      panelIds.add(panelId);
    });

    expect(triggerIds.size).toBe(7);
    expect(panelIds.size).toBe(7);
  });

  it("keeps heading, trigger, and panel IDs unique across FAQ instances", () => {
    render(
      <MemoryRouter>
        <FAQ />
        <FAQ darkMode />
      </MemoryRouter>,
    );

    const faqRegions = screen.getAllByRole("region", { name: "Student FAQ" });
    const headings = screen.getAllByRole("heading", { name: "Student FAQ" });
    const triggers = screen.getAllByRole("button");
    const triggerIds = triggers.map((trigger) => trigger.id);
    const panelIds = triggers.map((trigger) => trigger.getAttribute("aria-controls"));

    expect(faqRegions).toHaveLength(2);
    expect(new Set(headings.map((heading) => heading.id)).size).toBe(2);
    expect(new Set(triggerIds).size).toBe(14);
    expect(new Set(panelIds).size).toBe(14);

    triggers.forEach((trigger) => {
      const panelId = trigger.getAttribute("aria-controls");
      expect(document.querySelectorAll(`[id="${panelId}"]`)).toHaveLength(1);
      expect(controlledPanel(trigger)).toHaveAttribute("aria-labelledby", trigger.id);
    });
  });

  it("keeps one panel open at a time and lets the open trigger close it", () => {
    renderFAQ();

    const accountTrigger = screen.getByRole("button", {
      name: "How do I create a student account?",
    });
    const signInTrigger = screen.getByRole("button", { name: "How do I sign in?" });
    const accountPanel = controlledPanel(accountTrigger);
    const signInPanel = controlledPanel(signInTrigger);

    fireEvent.click(accountTrigger);
    expect(accountTrigger).toHaveAttribute("aria-expanded", "true");
    expect(accountPanel).not.toHaveAttribute("hidden");

    fireEvent.click(signInTrigger);
    expect(accountTrigger).toHaveAttribute("aria-expanded", "false");
    expect(accountPanel).toHaveAttribute("hidden");
    expect(signInTrigger).toHaveAttribute("aria-expanded", "true");
    expect(signInPanel).not.toHaveAttribute("hidden");

    fireEvent.click(signInTrigger);
    expect(signInTrigger).toHaveAttribute("aria-expanded", "false");
    expect(signInPanel).toHaveAttribute("hidden");
  });

  it("warns that post drafts are tab-only and explains save, resume, and discard", () => {
    renderFAQ();

    const trigger = screen.getByRole("button", { name: "How do post drafts work?" });
    fireEvent.click(trigger);
    const panel = controlledPanel(trigger);

    expect(panel).toHaveTextContent(/Save Draft/);
    expect(panel).toHaveTextContent(/Resume/);
    expect(panel).toHaveTextContent(/Discard Draft/);
    expect(panel).toHaveTextContent(/Post drafts are tab-only/i);
    expect(panel).toHaveTextContent(/refreshing the page/i);
    expect(panel).toHaveTextContent(/closing the tab/i);
    expect(panel).toHaveTextContent(/signing out clears them/i);
  });

  it("states the current upload formats and size limits", () => {
    renderFAQ();

    const trigger = screen.getByRole("button", {
      name: "How do I add or remove images, videos, and PDFs?",
    });
    fireEvent.click(trigger);
    const panel = controlledPanel(trigger);

    expect(panel).toHaveTextContent(/Images.*JPG\/JPEG, PNG, GIF, WebP, or BMP.*10 MB/i);
    expect(panel).toHaveTextContent(/PDFs.*PDF.*25 MB/i);
    expect(panel).toHaveTextContent(/Videos.*MP4, M4V, WebM, MKV, OGG, or AVI.*100 MB/i);
  });

  it("uses accurate app routes and exposes four honest future screenshot slots", () => {
    renderFAQ();

    const routes = Array.from(document.querySelectorAll("a"), (link) => link.getAttribute("href"));
    expect(routes).toEqual(expect.arrayContaining([
      "/sign-up",
      "/sign-in",
      "/student-hub",
      "/help",
      "/forgot-password",
    ]));

    const slots = Array.from(document.querySelectorAll("[data-faq-screenshot-slot]"));
    expect(slots).toHaveLength(4);
    expect(slots.map((slot) => slot.getAttribute("data-faq-screenshot-slot"))).toEqual([
      "signUp",
      "signIn",
      "joinClass",
      "postEditor",
    ]);
    slots.forEach((slot) => {
      expect(slot).toHaveTextContent("Current screenshot will appear here.");
    });
    expect(document.querySelector("img.faq-guide__image")).not.toBeInTheDocument();
  });

  it("renders a configured screenshot with lazy, descriptive, responsive media", () => {
    renderFAQ({
      screenshots: {
        signUp: { src: "/faq-sign-up.webp" },
      },
    });

    fireEvent.click(screen.getByRole("button", {
      name: "How do I create a student account?",
    }));

    const image = screen.getByRole("img", {
      name: "LitBlog student sign-up form with the Student role selected.",
    });

    expect(image).toHaveAttribute("src", "/faq-sign-up.webp");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("width", "1440");
    expect(image).toHaveAttribute("height", "900");
    expect(image).toHaveClass("faq-guide__image");
  });
});
