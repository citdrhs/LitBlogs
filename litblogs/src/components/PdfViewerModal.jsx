import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { Worker, Viewer } from '@react-pdf-viewer/core';
import { defaultLayoutPlugin } from '@react-pdf-viewer/default-layout';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url';
import '@react-pdf-viewer/core/lib/styles/index.css';
import '@react-pdf-viewer/default-layout/lib/styles/index.css';

const PDF_WORKER_URL = pdfWorkerUrl;

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
  width: 'min(1100px, 95vw)',
  height: 'min(850px, 90vh)',
  backgroundColor: '#ffffff',
  borderRadius: '12px',
  overflow: 'hidden',
  boxShadow: '0 20px 45px rgba(0, 0, 0, 0.35)',
  display: 'flex',
  flexDirection: 'column',
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

const PDF_LAYER_FIX_STYLES = `
  .inline-pdf-root {
    width: 100%;
    max-width: 100%;
    background: #fff;
  }

  .inline-pdf-root .rpv-core__viewer,
  .inline-pdf-root .rpv-core__page-layer,
  .inline-pdf-root .rpv-core__inner-page,
  .inline-pdf-root .rpv-core__text-layer,
  .inline-pdf-root .rpv-core__text-layer * {
    font-family: initial !important;
    text-shadow: none !important;
  }

  .inline-pdf-root .rpv-core__text-layer,
  .inline-pdf-root .rpv-core__text-layer * {
    color: transparent !important;
    -webkit-text-fill-color: transparent !important;
  }
`;

const InlinePdfViewer = ({ fileUrl, title = 'PDF Document' }) => {
  const defaultLayoutPluginInstance = defaultLayoutPlugin();

  return (
    <div className="inline-pdf-root" style={{ border: '1px solid #e5e7eb', borderRadius: '10px', overflow: 'hidden', margin: '12px 0', width: '100%', maxWidth: '100%' }}>
      <style>{PDF_LAYER_FIX_STYLES}</style>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #e5e7eb', backgroundColor: '#f8fafc', color: '#0f172a', fontWeight: 600 }}>
        {title}
      </div>
      <div style={{ height: '620px' }}>
        <Worker workerUrl={PDF_WORKER_URL}>
          <Viewer fileUrl={fileUrl} plugins={[defaultLayoutPluginInstance]} />
        </Worker>
      </div>
    </div>
  );
};

const PdfViewerModal = ({ fileUrl, title = 'PDF Preview', onClose }) => {
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  if (!fileUrl) {
    return null;
  }

  return (
    <div style={overlayStyles} onClick={onClose} role="presentation">
      <div style={modalStyles} onClick={(event) => event.stopPropagation()}>
        <div style={headerStyles}>
          <div style={{ fontWeight: 600, color: '#111827' }}>{title}</div>
          <button type="button" aria-label="Close PDF preview" style={closeButtonStyles} onClick={onClose}>
            &times;
          </button>
        </div>

        <div style={{ flex: 1, minHeight: 0 }}>
          <Worker workerUrl={PDF_WORKER_URL}>
            <Viewer fileUrl={fileUrl} />
          </Worker>
        </div>
      </div>
    </div>
  );
};

export const openPdfViewerModal = ({ fileUrl, title }) => {
  if (!fileUrl) {
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
    if (!fileUrl) {
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
