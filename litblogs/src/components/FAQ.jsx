import { useId, useState } from "react";
import { Link } from "react-router-dom";

import "../styles/faq.css";

const FAQ_SCREENSHOTS = Object.freeze({
  signUp: Object.freeze({
    slot: "signUp",
    src: null,
    alt: "LitBlog student sign-up form with the Student role selected.",
    width: 1440,
    height: 900,
    caption: "Create your student account.",
  }),
  signIn: Object.freeze({
    slot: "signIn",
    src: null,
    alt: "LitBlog sign-in page with school account and email sign-in options.",
    width: 1440,
    height: 900,
    caption: "Use the same sign-in method you registered with.",
  }),
  joinClass: Object.freeze({
    slot: "joinClass",
    src: null,
    alt: "Student Hub with the Join a Class dialog open for a teacher-provided class code.",
    width: 1440,
    height: 900,
    caption: "Join a class from Student Hub.",
  }),
  postEditor: Object.freeze({
    slot: "postEditor",
    src: null,
    alt: "Class feed post composer showing the title, rich-text toolbar, and Publish button.",
    width: 1440,
    height: 900,
    caption: "Write and publish from the class feed.",
  }),
});

const FAQ_ITEMS = Object.freeze([
  {
    id: "create-student-account",
    question: "How do I create a student account?",
    steps: [
      {
        before: "From the LitBlog home page, select Start Writing Now, or open ",
        link: { to: "/sign-up", label: "Create a student account" },
        after: ".",
      },
      {
        text: "Choose Student, then use your verified school Google or Microsoft account. If your school enables email registration, you can complete the name, email, and password fields instead.",
      },
      {
        before: "Submit the form, then ",
        link: { to: "/sign-in", label: "sign in" },
        after: " with the same method you used to register.",
      },
    ],
    screenshot: FAQ_SCREENSHOTS.signUp,
  },
  {
    id: "sign-in",
    question: "How do I sign in?",
    steps: [
      {
        before: "Open the ",
        link: { to: "/sign-in", label: "LitBlog sign-in page" },
        after: ".",
      },
      {
        text: "Choose the same Google, Microsoft, or email-and-password method you used when creating your account.",
      },
      {
        before: "After sign-in, open ",
        link: { to: "/student-hub", label: "Student Hub" },
        after: " to see your classes and posts.",
      },
    ],
    screenshot: FAQ_SCREENSHOTS.signIn,
  },
  {
    id: "join-class",
    question: "How can I join my teacher's class?",
    steps: [
      {
        before: "After signing in, open ",
        link: { to: "/student-hub", label: "Student Hub" },
        after: ".",
      },
      {
        text: "Select Join Class to open the Join a Class dialog.",
      },
      {
        text: "Enter the class code exactly as your teacher provided it, then select Join Class again.",
      },
      {
        text: "Choose the new class card to open its class feed.",
      },
    ],
    screenshot: FAQ_SCREENSHOTS.joinClass,
  },
  {
    id: "publish-post",
    question: "How do I create, format, and publish a post?",
    steps: [
      {
        before: "Open ",
        link: { to: "/student-hub", label: "Student Hub" },
        after: ", then choose the class where the post belongs.",
      },
      {
        text: "Select Create New Post, add a clear title, and write your post in the editor.",
      },
      {
        text: "Use the rich-text toolbar for headings, bold or italic text, lists, alignment, links, and other formatting.",
      },
      {
        before: "Review your work, wait for any media uploads to finish, then select Publish. Reopen the ",
        link: { to: "/help", label: "Help guide" },
        after: " whenever you want the full walkthrough.",
      },
    ],
    screenshot: FAQ_SCREENSHOTS.postEditor,
  },
  {
    id: "upload-media",
    question: "How do I add or remove images, videos, and PDFs?",
    steps: [
      {
        text: "In the post composer, place the cursor where the media belongs and choose the image, video, or PDF control in the rich-text toolbar.",
      },
      {
        label: "Images",
        text: "JPG/JPEG, PNG, GIF, WebP, or BMP; up to 10 MB.",
      },
      {
        label: "PDFs",
        text: "PDF only; up to 25 MB.",
      },
      {
        label: "Videos",
        text: "MP4, M4V, WebM, MKV, OGG, or AVI; up to 100 MB.",
      },
      {
        text: "To remove an upload before publishing, select it in the editor, then choose Remove image, Remove video, or Remove PDF.",
      },
    ],
  },
  {
    id: "post-drafts",
    question: "How do post drafts work?",
    steps: [
      {
        text: "While writing, select Save Draft to keep the unfinished post in your current browser tab.",
      },
      {
        text: "Close the composer, find Your Drafts on the class feed, and select Resume to continue writing.",
      },
      {
        text: "Select Discard Draft in the composer and confirm when you no longer need the draft.",
      },
      {
        text: "From Your Drafts, select Delete to remove a saved draft immediately.",
      },
    ],
    note: {
      label: "Keep this tab open",
      text: "Post drafts are tab-only. Refreshing the page, closing the tab or browser, or signing out clears them.",
    },
  },
  {
    id: "reset-password",
    question: "I forgot my password. How do I reset it?",
    steps: [
      {
        before: "Open ",
        link: { to: "/sign-in", label: "Sign In" },
        after: " and select Forgot Password.",
      },
      {
        before: "On the ",
        link: { to: "/forgot-password", label: "password reset page" },
        after: ", enter your account email and select Send Reset Instructions.",
      },
      {
        text: "Open the reset link sent to your email, choose a new password, confirm it, and select Reset Password.",
      },
      {
        before: "Return to ",
        link: { to: "/sign-in", label: "Sign In" },
        after: " and use your new password. If you registered with Google or Microsoft, sign in with that provider instead.",
      },
    ],
  },
]);

const FAQStep = ({ step }) => (
  <li>
    {step.label && <strong>{step.label}: </strong>}
    {step.before}
    {step.link && (
      <Link className="faq-guide__link" to={step.link.to}>
        {step.link.label}
      </Link>
    )}
    {step.after}
    {step.text}
  </li>
);

const FAQ = ({ darkMode = false, screenshots = {} }) => {
  const [activeId, setActiveId] = useState(null);
  const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const headingId = `student-faq-title-${instanceId}`;

  return (
    <section
      className={`faq-guide${darkMode ? " faq-guide--dark" : ""}`}
      aria-labelledby={headingId}
    >
      <header className="faq-guide__header">
        <p className="faq-guide__eyebrow">Frequently asked questions</p>
        <h2 id={headingId}>Student FAQ</h2>
        <p>Seven quick guides for getting from your first sign-in to a published post.</p>
      </header>

      <div className="faq-guide__list">
        {FAQ_ITEMS.map((item, index) => {
          const isOpen = activeId === item.id;
          const triggerId = `faq-trigger-${instanceId}-${item.id}`;
          const panelId = `faq-panel-${instanceId}-${item.id}`;
          const screenshot = item.screenshot
            ? { ...item.screenshot, ...screenshots?.[item.screenshot.slot] }
            : null;

          return (
            <article
              className={`faq-guide__item${isOpen ? " faq-guide__item--open" : ""}`}
              key={item.id}
              style={{ "--faq-delay": `${index * 45}ms` }}
            >
              <h3 className="faq-guide__question">
                <button
                  id={triggerId}
                  type="button"
                  className="faq-guide__trigger"
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  onClick={() => setActiveId(isOpen ? null : item.id)}
                >
                  <span>{item.question}</span>
                  <svg
                    className="faq-guide__chevron"
                    aria-hidden="true"
                    viewBox="0 0 20 20"
                    focusable="false"
                  >
                    <path d="m5 7.5 5 5 5-5" />
                  </svg>
                </button>
              </h3>

              <section
                id={panelId}
                role="region"
                className="faq-guide__panel"
                aria-labelledby={triggerId}
                hidden={!isOpen}
              >
                <div className="faq-guide__panel-inner">
                  <ol className="faq-guide__steps">
                    {item.steps.map((step, stepIndex) => (
                      <FAQStep key={`${item.id}-step-${stepIndex + 1}`} step={step} />
                    ))}
                  </ol>

                  {item.note && (
                    <aside className="faq-guide__note">
                      <strong>{item.note.label}</strong>
                      <span>{item.note.text}</span>
                    </aside>
                  )}

                  {screenshot && (
                    <figure
                      className="faq-guide__figure"
                      data-faq-screenshot-slot={screenshot.slot}
                    >
                      {screenshot.src ? (
                        <img
                          className="faq-guide__image"
                          src={screenshot.src}
                          alt={screenshot.alt}
                          width={screenshot.width}
                          height={screenshot.height}
                          loading="lazy"
                        />
                      ) : (
                        <div className="faq-guide__media-placeholder">
                          <span aria-hidden="true">▧</span>
                          <strong>Current screenshot will appear here.</strong>
                        </div>
                      )}
                      <figcaption>{screenshot.caption}</figcaption>
                    </figure>
                  )}
                </div>
              </section>
            </article>
          );
        })}
      </div>
    </section>
  );
};

export default FAQ;
