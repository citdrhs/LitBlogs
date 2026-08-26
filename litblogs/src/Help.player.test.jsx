import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Help from "./Help.jsx";

vi.mock("./components/Navbar.jsx", () => ({
  default: () => <nav aria-label="Primary" />,
}));

vi.mock("./components/Footer.jsx", () => ({
  default: () => <footer />,
}));

vi.mock("./components/FAQ.jsx", () => ({
  default: () => <section aria-label="Student FAQ" />,
}));

const renderHelp = () => render(
  <MemoryRouter>
    <Help />
  </MemoryRouter>,
);

describe("Help tutorial", () => {
  beforeEach(() => {
    localStorage.setItem("darkMode", "false");
  });

  it("renders non-autoplay tutorial media with a poster and default English captions", () => {
    const { container } = renderHelp();
    const video = screen.getByLabelText("LitBlog student tutorial");
    const source = container.querySelector("video source");
    const captions = container.querySelector("video track");

    expect(video).toHaveAttribute("preload", "metadata");
    expect(video).not.toHaveAttribute("autoplay");
    expect(video).toHaveAttribute("playsinline");
    expect(video.getAttribute("poster")).toContain(
      "/src/assets/tutorial/litblogs-tutorial-poster.jpg",
    );
    expect(source.getAttribute("src")).toContain(
      "/src/assets/tutorial/litblogs-tutorial.mp4",
    );
    expect(video.getAttribute("poster")).not.toBe("/tutorial/litblogs-tutorial.jpg");
    expect(source.getAttribute("src")).not.toBe("/tutorial/litblogs-tutorial.mp4");
    expect(source).toHaveAttribute("type", "video/mp4");
    expect(captions.getAttribute("src")).toContain(
      "/src/assets/tutorial/litblogs-tutorial.en.vtt",
    );
    expect(captions.getAttribute("src")).not.toBe("/tutorial/litblogs-tutorial.en.vtt");
    expect(captions).toHaveAttribute("kind", "captions");
    expect(captions).toHaveAttribute("srclang", "en");
    expect(captions).toHaveAttribute("label", "English");
    expect(captions).toHaveAttribute("default");
  });

  it("offers the approved student walkthrough as readable text and a download", () => {
    renderHelp();

    fireEvent.click(screen.getByText("Read tutorial transcript"));

    expect(screen.getByText("Welcome to LitBlog")).toBeInTheDocument();
    expect(screen.getByText("Sign up")).toBeInTheDocument();
    expect(screen.getByText("Register and sign in")).toBeInTheDocument();
    expect(screen.getByText(/six-character code from your teacher/)).toBeInTheDocument();
    expect(screen.getByText(/Select Create New Post/)).toBeInTheDocument();
    expect(screen.getByText(/choose Bold.*highlight color/i)).toBeInTheDocument();
    expect(screen.getByText(/Review your work, then select Publish/)).toBeInTheDocument();
    expect(screen.getByText(/class feed with bold and highlighting preserved/)).toBeInTheDocument();
    const transcriptLink = screen.getByRole("link", { name: "Download transcript" });
    expect(transcriptLink.getAttribute("href")).toContain(
      "/src/assets/tutorial/litblogs-tutorial-transcript.txt",
    );
    expect(transcriptLink.getAttribute("href")).not.toBe("/tutorial/litblogs-tutorial.txt");
  });
});
