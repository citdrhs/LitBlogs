import { useEffect, useMemo, useRef } from "react";

import "../styles/rich-text-content.css";
import { normalizeRichTextUrl, sanitizeRichText } from "../utils/richTextSecurity";
import { openPdfViewerModal } from "./PdfViewerModal";

const RichTextContent = ({
  html = "",
  compact = false,
  dark = false,
  className = "",
  testId,
  ariaLabel,
}) => {
  const contentRef = useRef(null);
  const sanitizedHtml = useMemo(() => {
    try {
      return sanitizeRichText(typeof html === "string" ? html : "", { mode: "render" });
    } catch {
      return "";
    }
  }, [html]);

  const classes = [
    "rich-text-content",
    compact ? "rich-text-content--compact" : "",
    dark ? "rich-text-content--dark" : "",
    className,
  ].filter(Boolean).join(" ");

  useEffect(() => {
    const content = contentRef.current;
    if (!content) return undefined;

    const attachments = content.querySelectorAll(".file-attachment[data-file-url]");
    for (const attachment of attachments) {
      const fileUrl = normalizeRichTextUrl(attachment.getAttribute("data-file-url"), "pdf");
      if (!fileUrl) continue;
      const fileName = attachment.getAttribute("data-file-name")
        || attachment.querySelector(".file-name")?.textContent?.trim()
        || "PDF document";
      attachment.setAttribute("role", "button");
      attachment.setAttribute("tabindex", "0");
      attachment.setAttribute("aria-label", `Open PDF ${fileName}`);
    }

    const openAttachment = (target) => {
      const attachment = target instanceof Element
        ? target.closest(".file-attachment[data-file-url]")
        : null;
      if (!attachment || !content.contains(attachment)) return false;
      const fileUrl = normalizeRichTextUrl(attachment.getAttribute("data-file-url"), "pdf");
      if (!fileUrl) return false;
      const title = attachment.getAttribute("data-file-name")
        || attachment.querySelector(".file-name")?.textContent?.trim()
        || "PDF document";
      openPdfViewerModal({ fileUrl, title });
      return true;
    };
    const handleClick = (event) => {
      if (openAttachment(event.target)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    const handleKeyDown = (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (openAttachment(event.target)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    content.addEventListener("click", handleClick);
    content.addEventListener("keydown", handleKeyDown);
    return () => {
      content.removeEventListener("click", handleClick);
      content.removeEventListener("keydown", handleKeyDown);
    };
  }, [sanitizedHtml]);

  return (
    <div
      ref={contentRef}
      className={classes}
      data-testid={testId}
      aria-label={ariaLabel}
      dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
    />
  );
};

export default RichTextContent;
