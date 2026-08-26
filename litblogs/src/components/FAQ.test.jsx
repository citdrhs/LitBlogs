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

const openPanel = (question) => {
  const trigger = screen.getByRole("button", { name: question });
  fireEvent.click(trigger);
  return controlledPanel(trigger);
};

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

  it("explains how to create a student account and links each next step", () => {
    renderFAQ();

    const panel = openPanel("How do I create a student account?");

    expect(within(panel).getByRole("link", { name: "Create a student account" }))
      .toHaveAttribute("href", "/sign-up");
    expect(panel).toHaveTextContent(/Choose Student/);
    expect(panel).toHaveTextContent(/Google or Microsoft account/);
    expect(panel).toHaveTextContent(/school enables email registration/);
    expect(within(panel).getByRole("link", { name: "sign in" }))
      .toHaveAttribute("href", "/sign-in");
  });

  it("explains sign-in methods and the route to Student Hub", () => {
    renderFAQ();

    const panel = openPanel("How do I sign in?");

    expect(within(panel).getByRole("link", { name: "LitBlog sign-in page" }))
      .toHaveAttribute("href", "/sign-in");
    expect(panel).toHaveTextContent(/same Google, Microsoft, or email-and-password method/);
    expect(within(panel).getByRole("link", { name: "Student Hub" }))
      .toHaveAttribute("href", "/student-hub");
  });

  it("explains the complete join-class flow inside its panel", () => {
    renderFAQ();

    const panel = openPanel("How can I join my teacher's class?");

    expect(panel).toHaveTextContent(/After signing in/);
    expect(within(panel).getByRole("link", { name: "Student Hub" }))
      .toHaveAttribute("href", "/student-hub");
    expect(panel).toHaveTextContent(/Select Join Class to open the Join a Class dialog/);
    expect(panel).toHaveTextContent(/class code exactly as your teacher provided it/);
    expect(panel).toHaveTextContent(/new class card to open its class feed/);
  });

  it("explains how to create, format, and publish from a class feed", () => {
    renderFAQ();

    const panel = openPanel("How do I create, format, and publish a post?");

    expect(within(panel).getByRole("link", { name: "Student Hub" }))
      .toHaveAttribute("href", "/student-hub");
    expect(panel).toHaveTextContent(/choose the class where the post belongs/);
    expect(panel).toHaveTextContent(/Select Create New Post/);
    expect(panel).toHaveTextContent(/add a clear title, and write your post/);
    expect(panel).toHaveTextContent(/rich-text toolbar for headings, bold or italic text, lists, alignment, links/);
    expect(panel).toHaveTextContent(/select Publish/);
    expect(within(panel).getByRole("link", { name: "Help guide" }))
      .toHaveAttribute("href", "/help");
  });

  it("warns that post drafts are tab-only and distinguishes discard from immediate delete", () => {
    renderFAQ();

    const panel = openPanel("How do post drafts work?");

    expect(panel).toHaveTextContent(/Save Draft/);
    expect(panel).toHaveTextContent(/Resume/);
    expect(panel).toHaveTextContent(
      "Select Discard Draft in the composer and confirm when you no longer need the draft.",
    );
    expect(panel).toHaveTextContent(
      "From Your Drafts, select Delete to remove a saved draft immediately.",
    );
    expect(panel).not.toHaveTextContent(/Delete beside a saved draft, and confirm/);
    expect(panel).toHaveTextContent(/Post drafts are tab-only/i);
    expect(panel).toHaveTextContent(/refreshing the page/i);
    expect(panel).toHaveTextContent(/closing the tab/i);
    expect(panel).toHaveTextContent(/signing out clears them/i);
  });

  it("explains upload and removal controls with current formats and limits", () => {
    renderFAQ();

    const panel = openPanel("How do I add or remove images, videos, and PDFs?");

    expect(panel).toHaveTextContent(/place the cursor where the media belongs/);
    expect(panel).toHaveTextContent(/image, video, or PDF control in the rich-text toolbar/);
    expect(panel).toHaveTextContent(/Images.*JPG\/JPEG, PNG, GIF, WebP, or BMP.*10 MB/i);
    expect(panel).toHaveTextContent(/PDFs.*PDF.*25 MB/i);
    expect(panel).toHaveTextContent(/Videos.*MP4, M4V, WebM, MKV, OGG, or AVI.*100 MB/i);
    expect(panel).toHaveTextContent(/select it in the editor/);
    expect(panel).toHaveTextContent(/Remove image, Remove video, or Remove PDF/);
  });

  it("explains the complete forgotten-password reset flow and routes", () => {
    renderFAQ();

    const panel = openPanel("I forgot my password. How do I reset it?");
    const signInLinks = within(panel).getAllByRole("link", { name: "Sign In" });

    expect(signInLinks).toHaveLength(2);
    signInLinks.forEach((link) => expect(link).toHaveAttribute("href", "/sign-in"));
    expect(panel).toHaveTextContent(/select Forgot Password/);
    expect(within(panel).getByRole("link", { name: "password reset page" }))
      .toHaveAttribute("href", "/forgot-password");
    expect(panel).toHaveTextContent(/select Send Reset Instructions/);
    expect(panel).toHaveTextContent(/Open the reset link sent to your email/);
    expect(panel).toHaveTextContent(/choose a new password, confirm it, and select Reset Password/);
    expect(panel).toHaveTextContent(/Google or Microsoft/);
  });

  it("uses accurate app routes and renders four distinct guided screenshots by default", () => {
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
    const sources = slots.map((slot) => {
      const image = slot.querySelector("img.faq-guide__image");
      expect(image).toBeInTheDocument();
      expect(image).toHaveAttribute("loading", "lazy");
      expect(image).toHaveAttribute("width", "1440");
      expect(image).toHaveAttribute("height", "900");
      expect(image.getAttribute("alt")).not.toHaveLength(0);
      expect(image.getAttribute("src")).not.toHaveLength(0);
      return image.getAttribute("src");
    });
    expect(new Set(sources).size).toBe(4);
    expect(document.querySelector(".faq-guide__media-placeholder")).not.toBeInTheDocument();
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
      name: "Annotated LitBlog student sign-up form with Jordan Reader's school email, masked passwords, Student role, and Sign Up button.",
    });

    expect(image).toHaveAttribute("src", "/faq-sign-up.webp");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("width", "1440");
    expect(image).toHaveAttribute("height", "900");
    expect(image).toHaveClass("faq-guide__image");
  });
});
