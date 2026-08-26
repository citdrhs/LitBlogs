import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";

export const FAQ_STILLS = Object.freeze({
  FAQSignUp: {
    captureAsset: "captures/signup-filled.jpg",
    eyebrow: "Student guide 01",
    title: "Create your LitBlog account",
    description: "Use your school details, choose Student, then submit the completed form.",
    callouts: [
      { number: 1, title: "School details", detail: "Enter your name and school email.", x: 1018, y: 226 },
      { number: 2, title: "Strong password", detail: "Confirm the same secure password.", x: 1018, y: 392 },
      { number: 3, title: "Student role", detail: "Choose Student, then Sign Up.", x: 1018, y: 558 },
    ],
  },
  FAQSignIn: {
    captureAsset: "captures/signin-filled.jpg",
    eyebrow: "Student guide 02",
    title: "Sign in with the same credentials",
    description: "Return to Sign In after registration and use the same school email and password.",
    callouts: [
      { number: 1, title: "Same email", detail: "Use the school email you registered.", x: 1018, y: 252 },
      { number: 2, title: "Same password", detail: "Your password remains masked on screen.", x: 1018, y: 418 },
      { number: 3, title: "Open Student Hub", detail: "Select Sign In to continue.", x: 1018, y: 584 },
    ],
  },
  FAQJoinClass: {
    captureAsset: "captures/join-class-code.jpg",
    eyebrow: "Student guide 03",
    title: "Join your teacher's class",
    description: "Open Join Class from Student Hub and enter the six-character code from your teacher.",
    callouts: [
      { number: 1, title: "Open the dialog", detail: "Select Join Class in Student Hub.", x: 1018, y: 252 },
      { number: 2, title: "Enter the code", detail: "Type all six letters and numbers.", x: 1018, y: 418 },
      { number: 3, title: "Confirm", detail: "Select Join Class again.", x: 1018, y: 584 },
    ],
  },
  FAQPostEditor: {
    captureAsset: "captures/post-formatted.jpg",
    eyebrow: "Student guide 04",
    title: "Write, format, and publish",
    description: "Add a clear title, write your response, then use Bold and amber Highlight before publishing.",
    callouts: [
      { number: 1, title: "Clear title", detail: "Name the idea your post explores.", x: 1018, y: 226 },
      { number: 2, title: "Rich-text tools", detail: "Select text, then choose Bold.", x: 1018, y: 392 },
      { number: 3, title: "Amber highlight", detail: "Highlight important evidence.", x: 1018, y: 558 },
    ],
  },
});

export const FaqStill = ({ captureAsset, eyebrow, title, description, callouts }) => (
  <AbsoluteFill className="faq-still">
    <div className="faq-still__margin-line" />
    <header className="faq-still__header">
      <Img className="faq-still__logo" src={staticFile("brand/logo.png")} />
      <div>
        <p className="faq-still__eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="faq-still__description">{description}</p>
      </div>
    </header>

    <section className="faq-still__browser" aria-label="Current LitBlog interface capture">
      <div className="browser-chrome">
        <span className="browser-dot browser-dot--red" />
        <span className="browser-dot browser-dot--amber" />
        <span className="browser-dot browser-dot--green" />
        <div className="browser-address">litblog.school</div>
      </div>
      <div className="faq-still__capture">
        <Img src={staticFile(captureAsset)} />
      </div>
    </section>

    <aside className="faq-still__legend" aria-label="Numbered instructions">
      {callouts.map((callout) => (
        <div
          key={callout.number}
          className="faq-still__callout"
          style={{ left: callout.x, top: callout.y }}
        >
          <span>{callout.number}</span>
          <div>
            <strong>{callout.title}</strong>
            <p>{callout.detail}</p>
          </div>
        </div>
      ))}
    </aside>

    <footer className="faq-still__footer">
      <span>LitBlog student guide</span>
      <span>Real interface · synthetic tutorial data</span>
    </footer>
  </AbsoluteFill>
);
