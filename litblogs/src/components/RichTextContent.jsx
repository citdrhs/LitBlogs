import { useMemo } from "react";

import "../styles/rich-text-content.css";
import { sanitizeRichText } from "../utils/richTextSecurity";

const RichTextContent = ({
  html = "",
  compact = false,
  className = "",
  testId,
  ariaLabel,
}) => {
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
    className,
  ].filter(Boolean).join(" ");

  return (
    <div
      className={classes}
      data-testid={testId}
      aria-label={ariaLabel}
      dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
    />
  );
};

export default RichTextContent;
