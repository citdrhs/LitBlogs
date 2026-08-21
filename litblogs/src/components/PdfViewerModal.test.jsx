import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import PdfViewerModal from './PdfViewerModal';

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
    'http://files.example.test/course-reading.pdf',
    '//files.example.test/course-reading.pdf',
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

  it('closes from the button, Escape key, and backdrop but not from dialog content', () => {
    const onClose = vi.fn();
    render(
      <PdfViewerModal fileUrl="/api/uploads/course-reading.pdf" onClose={onClose} />,
    );

    const dialog = screen.getByRole('dialog', { name: 'PDF Preview' });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(dialog.parentElement);
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('button', { name: 'Close PDF preview' }));
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
