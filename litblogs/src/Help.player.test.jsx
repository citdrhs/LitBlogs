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
    expect(video).toHaveAttribute("poster", "/tutorial/litblogs-tutorial.jpg");
    expect(source).toHaveAttribute("src", "/tutorial/litblogs-tutorial.mp4");
    expect(source).toHaveAttribute("type", "video/mp4");
    expect(captions).toHaveAttribute("src", "/tutorial/litblogs-tutorial.en.vtt");
    expect(captions).toHaveAttribute("kind", "captions");
    expect(captions).toHaveAttribute("srclang", "en");
    expect(captions).toHaveAttribute("label", "English");
    expect(captions).toHaveAttribute("default");
  });

  it("offers the approved student walkthrough as readable text and a download", () => {
    renderHelp();

    fireEvent.click(screen.getByText("Read tutorial transcript"));

    expect(screen.getByText(/Create your student account/)).toBeInTheDocument();
    expect(screen.getByText(/Sign in with the same method/)).toBeInTheDocument();
    expect(screen.getByText(/Join Class/)).toBeInTheDocument();
    expect(screen.getByText(/Create New Post/)).toBeInTheDocument();
    expect(screen.getByText(/Bold and Highlight/)).toBeInTheDocument();
    expect(screen.getByText(/select Publish/)).toBeInTheDocument();
    expect(screen.getByText(/open the published post/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download transcript" }))
      .toHaveAttribute("href", "/tutorial/litblogs-tutorial.txt");
  });
});
