import { useEffect, useId } from 'react';
import { createRoot } from 'react-dom/client';

const overlayStyles = {
  position: 'fixed',
  inset: 0,
  backgroundColor: 'rgba(0, 0, 0, 0.8)',
  zIndex: 10000,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '20px',
};

const modalStyles = {
  width: 'min(560px, 95vw)',
  backgroundColor: '#ffffff',
  borderRadius: '12px',
  overflow: 'hidden',
  boxShadow: '0 20px 45px rgba(0, 0, 0, 0.35)',
};

const headerStyles = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '10px 14px',
  borderBottom: '1px solid #e5e7eb',
};

const closeButtonStyles = {
  border: 'none',
  background: 'transparent',
  fontSize: '28px',
  lineHeight: 1,
  color: '#111827',
  cursor: 'pointer',
  padding: '2px 6px',
};

const contentStyles = {
  padding: '24px',
  color: '#334155',
};

const fileNameStyles = {
  margin: '0 0 12px',
  color: '#0f172a',
  fontWeight: 600,
  overflowWrap: 'anywhere',
};

const openLinkStyles = {
  display: 'inline-block',
  marginTop: '8px',
  padding: '10px 14px',
  borderRadius: '8px',
  backgroundColor: '#2563eb',
  color: '#ffffff',
  fontWeight: 600,
  textDecoration: 'none',
};

const hasUsableFileUrl = (fileUrl) => (
  typeof fileUrl === 'string' && fileUrl.trim().length > 0
);

const hasUnsafeUrlCharacters = (fileUrl) => Array.from(fileUrl).some((character) => {
  const codePoint = character.codePointAt(0);
  return codePoint <= 0x20
    || codePoint === 0x7f
    || character === '\\'
    || /\s/u.test(character);
});

const getSafeFileUrl = (fileUrl) => {
  if (
    !hasUsableFileUrl(fileUrl)
    || hasUnsafeUrlCharacters(fileUrl)
    || fileUrl.startsWith('//')
  ) {
    return null;
  }

  try {
    const parsedUrl = new URL(fileUrl, document.baseURI);
    if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
      return null;
    }
  } catch {
    return null;
  }

  return fileUrl;
};

const getFileName = (fileUrl) => {
  const path = fileUrl.split(/[?#]/, 1)[0];
  const encodedFileName = path.split('/').filter(Boolean).pop();

  if (!encodedFileName) {
    return 'PDF document';
  }

  try {
    return decodeURIComponent(encodedFileName);
  } catch {
    return encodedFileName;
  }
};

const SafePdfLink = ({ fileUrl, fileName }) => (
  <a
    href={fileUrl}
    target="_blank"
    rel="noopener noreferrer"
    download={fileName}
    style={openLinkStyles}
  >
    Open or download {fileName}
  </a>
);

const InlinePdfViewer = ({ fileUrl, title = 'PDF Document' }) => {
  if (!hasUsableFileUrl(fileUrl)) {
    return null;
  }

  const safeFileUrl = getSafeFileUrl(fileUrl);
  const fileName = safeFileUrl ? getFileName(safeFileUrl) : 'PDF document';

  return (
    <section
      className="inline-pdf-root"
      aria-label={title}
      style={{ border: '1px solid #e5e7eb', borderRadius: '10px', margin: '12px 0', padding: '16px', width: '100%', maxWidth: '100%', backgroundColor: '#ffffff' }}
    >
      <div style={{ color: '#0f172a', fontWeight: 600 }}>{title}</div>
      <p style={{ ...fileNameStyles, marginTop: '12px' }}>{fileName}</p>
      <p style={{ margin: 0 }}>
        {safeFileUrl
          ? 'This PDF is not rendered inside LitBlog.'
          : 'This PDF link cannot be opened safely.'}
      </p>
      {safeFileUrl && <SafePdfLink fileUrl={safeFileUrl} fileName={fileName} />}
    </section>
  );
};

const PdfViewerModal = ({ fileUrl, title = 'PDF Preview', onClose }) => {
  const titleId = useId();
  const descriptionId = useId();
  const isOpen = hasUsableFileUrl(fileUrl);
  const safeFileUrl = getSafeFileUrl(fileUrl);

  useEffect(() => {
    if (!isOpen || typeof onClose !== 'function') {
      return undefined;
    }

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  const fileName = safeFileUrl ? getFileName(safeFileUrl) : 'PDF document';

  return (
    <div
      style={overlayStyles}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose?.();
        }
      }}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        style={modalStyles}
      >
        <div style={headerStyles}>
          <h2 id={titleId} style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: '#111827' }}>{title}</h2>
          <button type="button" aria-label="Close PDF preview" style={closeButtonStyles} onClick={onClose} autoFocus>
            &times;
          </button>
        </div>

        <div style={contentStyles}>
          <p style={fileNameStyles}>{fileName}</p>
          <p id={descriptionId} style={{ margin: 0 }}>
            {safeFileUrl
              ? 'For safety, LitBlog does not render PDF files inside the application.'
              : 'This PDF link cannot be opened safely.'}
          </p>
          {safeFileUrl && <SafePdfLink fileUrl={safeFileUrl} fileName={fileName} />}
        </div>
      </div>
    </div>
  );
};

export const openPdfViewerModal = ({ fileUrl, title }) => {
  if (!hasUsableFileUrl(fileUrl)) {
    return;
  }

  const container = document.createElement('div');
  document.body.appendChild(container);

  const root = createRoot(container);

  const handleClose = () => {
    root.unmount();
    if (container.parentNode) {
      container.parentNode.removeChild(container);
    }
  };

  root.render(
    <PdfViewerModal
      fileUrl={fileUrl}
      title={title}
      onClose={handleClose}
    />
  );
};

export const mountInlinePdfViewers = (containerElement) => {
  if (!containerElement) {
    return () => {};
  }

  const placeholders = containerElement.querySelectorAll('[data-inline-pdf-viewer="true"]');
  const mounted = [];

  placeholders.forEach((placeholder) => {
    const fileUrl = placeholder.getAttribute('data-pdf-url');
    const title = placeholder.getAttribute('data-pdf-title') || 'PDF Document';
    if (!hasUsableFileUrl(fileUrl)) {
      return;
    }

    const root = createRoot(placeholder);
    root.render(<InlinePdfViewer fileUrl={fileUrl} title={title} />);
    mounted.push(root);
  });

  return () => {
    mounted.forEach((root) => root.unmount());
  };
};

export default PdfViewerModal;
