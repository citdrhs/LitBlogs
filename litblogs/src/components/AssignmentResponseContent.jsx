import RichTextContent from "./RichTextContent.jsx";
import { assignmentContentFormat } from "../utils/assignmentResponse.js";

const AssignmentResponseContent = ({ content, contentFormat, dark = false, className = "" }) => {
  if (!content) return null;
  if (assignmentContentFormat(contentFormat) === "rich") {
    return (
      <RichTextContent
        html={content}
        dark={dark}
        className={className}
      />
    );
  }
  return <div className={`whitespace-pre-wrap ${className}`}>{content}</div>;
};

export default AssignmentResponseContent;
