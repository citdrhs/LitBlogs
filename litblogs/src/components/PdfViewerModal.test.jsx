import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import PdfViewerModal from './PdfViewerModal';

const ModalHarness = ({ isOpen, onClose }) => (
  <>
    <button key="invoker" type="button">Open PDF preview</button>
    {isOpen && (
      <PdfViewerModal
        key="modal"
        fileUrl="/api/uploads/course-reading.pdf"
        onClose={onClose}
      />
    )}
    <button key="background" type="button">Background action</button>
  </>
);

const openModalFromInvoker = (onClose = vi.fn()) => {
  const view = render(<ModalHarness isOpen={false} onClose={onClose} />);
  const invoker = screen.getByRole('button', { name: 'Open PDF preview' });
  invoker.focus();

  view.rerender(<ModalHarness isOpen onClose={onClose} />);

  return {
    ...view,
    backgroundControl: screen.getByRole('button', { name: 'Background action' }),
    dialog: screen.getByRole('dialog', { name: 'PDF Preview' }),
    invoker,
    onClose,
  };
};

describe('PdfViewerModal', () => {
  it('renders nothing when the PDF URL is empty', () => {
    const { container, rerender } = render(
      <PdfViewerModal fileUrl="" title="Course reading" onClose={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();

    rerender(
      <PdfViewerModal fileUrl="   " title="Course reading" onClose={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    'javascript:alert(document.domain)',
    'data:text/html,<script>alert(document.domain)</script>',
    'vbscript:msgbox(document.domain)',
    'blob:https://litblog.example.test/8a6f4db0',
    'file:///C:/course-reading.pdf',
    '//files.example.test/x.pdf',
    '\\\\files.example.test\\x.pdf',
    ' javascript:alert(document.domain)',
    'java\nscript:alert(document.domain)',
    '\t//files.example.test/course-reading.pdf',
  ])('shows a safe fallback without linking the rejected URL %s', (fileUrl) => {
    const { container } = render(
      <PdfViewerModal fileUrl={fileUrl} title="Course reading" onClose={vi.fn()} />,
    );

    expect(screen.getByRole('dialog', { name: 'Course reading' })).toBeInTheDocument();
    expect(screen.getByText('This PDF link cannot be opened safely.')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(container.querySelector('script, iframe, object, embed')).not.toBeInTheDocument();
  });

  it.each([
    '/api/uploads/course-reading.pdf',
    './course-reading.pdf',
    '../course-reading.pdf',
    'http://files.example.test/course-reading.pdf',
  ])('preserves the safe web URL %s unchanged', (fileUrl) => {
    render(
      <PdfViewerModal fileUrl={fileUrl} title="Course reading" onClose={vi.fn()} />,
    );

    expect(screen.getByRole('link', {
      name: 'Open or download course-reading.pdf',
    })).toHaveAttribute('href', fileUrl);
  });

  it('offers the caller-provided PDF URL without rendering the document in application JavaScript', () => {
    const fileUrl = 'https://files.example.test/readings/Beloved%20Excerpt.pdf?token=opaque#page=2';
    const title = '<img src=x onerror=alert(1)> Course reading';
    const { container } = render(
      <PdfViewerModal fileUrl={fileUrl} title={title} onClose={vi.fn()} />,
    );

    const dialog = screen.getByRole('dialog', { name: title });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText('Beloved Excerpt.pdf')).toBeInTheDocument();

    const openLink = screen.getByRole('link', {
      name: 'Open or download Beloved Excerpt.pdf',
    });
    expect(openLink).toHaveAttribute('href', fileUrl);
    expect(openLink).toHaveAttribute('target', '_blank');
    expect(openLink).toHaveAttribute('rel', 'noopener noreferrer');

    expect(container.querySelector('canvas, iframe, object, embed')).not.toBeInTheDocument();
    expect(container.querySelector('[class*="rpv-core"], style')).not.toBeInTheDocument();
    expect(container.querySelector('img')).not.toBeInTheDocument();
  });

  it('opens a native dialog and moves focus inside it', () => {
    const { dialog, invoker } = openModalFromInvoker();

    expect(dialog.tagName).toBe('DIALOG');
    expect(invoker).not.toHaveFocus();
    expect(dialog).toContainElement(document.activeElement);
  });

  it('uses showModal when the native dialog API is available', () => {
    const originalShowModalDescriptor = Object.getOwnPropertyDescriptor(
      HTMLDialogElement.prototype,
      'showModal',
    );
    const originalCloseDescriptor = Object.getOwnPropertyDescriptor(
      HTMLDialogElement.prototype,
      'close',
    );
    const showModal = vi.fn(function showModal() {
      this.setAttribute('open', '');
    });
    const closeDialog = vi.fn(function closeDialog() {
      this.removeAttribute('open');
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value: showModal,
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value: closeDialog,
    });

    try {
      const { dialog, invoker, onClose } = openModalFromInvoker();

      expect(showModal).toHaveBeenCalledTimes(1);
      expect(dialog).toHaveAttribute('open');

      fireEvent.click(screen.getByRole('button', { name: 'Close PDF preview' }));
      expect(closeDialog).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(invoker).toHaveFocus();
    } finally {
      if (originalShowModalDescriptor) {
        Object.defineProperty(
          HTMLDialogElement.prototype,
          'showModal',
          originalShowModalDescriptor,
        );
      } else {
        delete HTMLDialogElement.prototype.showModal;
      }

      if (originalCloseDescriptor) {
        Object.defineProperty(
          HTMLDialogElement.prototype,
          'close',
          originalCloseDescriptor,
        );
      } else {
        delete HTMLDialogElement.prototype.close;
      }
    }
  });

  it('wraps forward and backward focus within the modal', () => {
    const { backgroundControl, dialog } = openModalFromInvoker();
    const closeButton = screen.getByRole('button', { name: 'Close PDF preview' });
    const openLink = screen.getByRole('link', { name: 'Open or download course-reading.pdf' });

    openLink.focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(closeButton).toHaveFocus();
    expect(backgroundControl).not.toHaveFocus();

    closeButton.focus();
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
    expect(openLink).toHaveFocus();
    expect(dialog).toContainElement(document.activeElement);

    backgroundControl.focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(closeButton).toHaveFocus();
  });

  it.each([
    ['close button', () => fireEvent.click(screen.getByRole('button', { name: 'Close PDF preview' }))],
    ['Escape key', () => fireEvent.keyDown(window, { key: 'Escape' })],
    ['cancel event', (dialog) => fireEvent(dialog, new Event('cancel', { cancelable: true }))],
    ['backdrop', (dialog) => fireEvent.click(dialog)],
  ])('restores invoker focus after the %s close path', (_name, closeModal) => {
    const { dialog, invoker, onClose } = openModalFromInvoker();

    closeModal(dialog);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(invoker).toHaveFocus();
  });

  it('restores invoker focus when the modal is removed by its parent', () => {
    const { invoker, onClose, rerender } = openModalFromInvoker();

    rerender(<ModalHarness isOpen={false} onClose={onClose} />);

    expect(invoker).toHaveFocus();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('does not restore focus to a disabled invoker', () => {
    const { invoker, onClose } = openModalFromInvoker();
    invoker.disabled = true;

    fireEvent.click(screen.getByRole('button', { name: 'Close PDF preview' }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(invoker).not.toHaveFocus();
  });

  it('does not restore focus to a disconnected invoker', () => {
    const invoker = document.createElement('button');
    invoker.type = 'button';
    document.body.appendChild(invoker);
    invoker.focus();
    const onClose = vi.fn();
    render(
      <PdfViewerModal
        fileUrl="/api/uploads/course-reading.pdf"
        onClose={onClose}
      />,
    );
    invoker.remove();

    fireEvent.click(screen.getByRole('button', { name: 'Close PDF preview' }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(invoker).not.toHaveFocus();
  });

  it('restores a connected external invoker when the component unmounts', () => {
    const invoker = document.createElement('button');
    invoker.type = 'button';
    document.body.appendChild(invoker);
    invoker.focus();
    const { unmount } = render(
      <PdfViewerModal
        fileUrl="/api/uploads/course-reading.pdf"
        onClose={vi.fn()}
      />,
    );

    unmount();

    expect(invoker).toHaveFocus();
    invoker.remove();
  });

  it('cleans up the fallback key handler and does not duplicate it on rerender', () => {
    const firstOnClose = vi.fn();
    const secondOnClose = vi.fn();
    const { rerender } = openModalFromInvoker(firstOnClose);

    rerender(<ModalHarness isOpen onClose={secondOnClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });

    expect(firstOnClose).not.toHaveBeenCalled();
    expect(secondOnClose).toHaveBeenCalledTimes(1);

    rerender(<ModalHarness isOpen={false} onClose={secondOnClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(secondOnClose).toHaveBeenCalledTimes(1);
  });

  it('closes from the button, Escape key, and backdrop but not from dialog content', () => {
    const onClose = vi.fn();
    render(
      <PdfViewerModal fileUrl="/api/uploads/course-reading.pdf" onClose={onClose} />,
    );

    const dialog = screen.getByRole('dialog', { name: 'PDF Preview' });
    fireEvent.click(screen.getByText('course-reading.pdf'));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(dialog);
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('button', { name: 'Close PDF preview' }));
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
