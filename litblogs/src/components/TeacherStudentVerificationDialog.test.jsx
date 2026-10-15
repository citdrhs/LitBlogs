import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TeacherStudentVerificationDialog from './TeacherStudentVerificationDialog';

const doubles = vi.hoisted(() => ({ post: vi.fn(), writeText: vi.fn() }));
vi.mock('axios', () => ({ default: { post: doubles.post } }));

const students = [
  { id: 1, first_name: 'Alex', last_name: 'Rivera', username: 'alexr', email: 'hcps-riveraa@henricostudents.org' },
  { id: 2, first_name: 'Jamie', last_name: 'Chen', username: 'jamiec', email: 'hcps-chenj@henricostudents.org' },
];
const expiresAt = '2099-10-15T16:15:00Z';
const codes = students.map((student, index) => ({
  ...student,
  student_id: student.id,
  code: ['012345', '693284'][index],
  expires_at: expiresAt,
}));

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Help students</button>
      {open && <TeacherStudentVerificationDialog darkMode={false} onClose={() => setOpen(false)} />}
    </>
  );
}

const openDialog = () => {
  render(<DialogHarness />);
  const invoker = screen.getByRole('button', { name: 'Help students' });
  invoker.focus();
  fireEvent.click(invoker);
  return screen.getByRole('dialog', { name: 'Verify students' });
};

const findStudents = async (emailText = students.map((student) => student.email).join('\n')) => {
  fireEvent.change(screen.getByLabelText('Student school email addresses'), { target: { value: emailText } });
  fireEvent.click(screen.getByRole('button', { name: 'Find students' }));
  await screen.findByRole('heading', { name: 'Select students to help' });
};

const selectAndCreate = async () => {
  await findStudents();
  for (const checkbox of screen.getAllByRole('checkbox')) fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole('button', { name: 'Create verification codes' }));
  await screen.findByRole('heading', { name: 'Student verification codes' });
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  doubles.writeText.mockReset().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: doubles.writeText },
  });
  doubles.post.mockReset().mockImplementation(async (path) => {
    if (path.endsWith('/lookup')) return { data: { students, unmatched_count: 1 } };
    if (path.endsWith('/codes')) return { data: { codes } };
    throw new Error('Unexpected endpoint');
  });
});

afterEach(() => vi.useRealTimers());

describe('teacher-assisted student verification', () => {
  it('normalizes exact addresses, requires selection, and creates separate private student codes', async () => {
    const dialog = openDialog();
    expect(screen.getByLabelText('Student school email addresses')).toHaveFocus();
    expect(within(dialog).getByText(/Confirm each student’s identity in person/)).toBeInTheDocument();
    await findStudents(` ${students[0].email.toUpperCase()};\n${students[1].email}, ${students[0].email}`);

    expect(doubles.post).toHaveBeenCalledWith('/teacher/student-verifications/lookup', {
      emails: students.map((student) => student.email),
    }, { signal: expect.any(AbortSignal) });
    expect(screen.getByRole('button', { name: 'Create verification codes' })).toBeDisabled();
    expect(screen.getByText(/Some addresses did not match/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Alex Rivera/ }));
    expect(screen.getByRole('status')).toHaveTextContent('1 of 2 selected');
    fireEvent.click(screen.getByRole('checkbox', { name: /Jamie Chen/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Create verification codes' }));

    await screen.findByRole('heading', { name: 'Student verification codes' });
    expect(doubles.post).toHaveBeenLastCalledWith('/teacher/student-verifications/codes', {
      emails: students.map((student) => student.email),
    }, { signal: expect.any(AbortSignal) });
    expect(screen.getByLabelText('Verification code for Alex Rivera')).toHaveValue('012345');
    expect(screen.getByLabelText('Verification code for Jamie Chen')).toHaveValue('693284');
    expect(screen.getByText(/Each code works once for 15 minutes/)).toBeInTheDocument();
    expect(screen.getByText(/Closing this window clears them/)).toBeInTheDocument();
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toMatch(/012345|693284/);
    expect(window.location.href).not.toMatch(/012345|693284/);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByDisplayValue('012345')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Help students' })).toHaveFocus();
  });

  it('shows generic guidance for empty or ineligible matches without offering codes', async () => {
    doubles.post.mockResolvedValue({ data: { students: [], unmatched_count: 2 } });
    openDialog();
    await findStudents();
    expect(screen.getByRole('status')).toHaveTextContent('No eligible unverified student accounts were found.');
    expect(screen.queryByRole('button', { name: 'Create verification codes' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Edit addresses' }));
    expect(screen.getByLabelText('Student school email addresses')).toHaveFocus();
  });

  it('copies only the chosen code and selects it for manual copying when clipboard access fails', async () => {
    openDialog();
    await selectAndCreate();
    fireEvent.click(screen.getByRole('button', { name: 'Copy code for Jamie Chen' }));
    await screen.findByText('Code copied.');
    expect(doubles.writeText).toHaveBeenCalledWith('693284');

    doubles.writeText.mockRejectedValueOnce(new Error('private clipboard detail'));
    fireEvent.click(screen.getByRole('button', { name: 'Copy code for Alex Rivera' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Copy failed. Select and copy the code above.');
    const codeInput = screen.getByLabelText('Verification code for Alex Rivera');
    expect(codeInput).toHaveFocus();
    expect(codeInput.selectionStart).toBe(0);
    expect(codeInput.selectionEnd).toBe(6);
    expect(dialogText()).not.toContain('private clipboard detail');
  });

  it.each([
    [400, 'Enter up to 25 valid student school email addresses.'],
    [403, 'Your teacher session is no longer available. Sign in again.'],
    [409, 'The selected accounts changed. Find the students again before creating codes.'],
    [429, 'Too many requests. Wait a few minutes before trying again.'],
    [503, 'The request could not be completed. Try again.'],
  ])('uses safe lookup errors for status %s', async (status, message) => {
    doubles.post.mockRejectedValueOnce({ response: { status, data: { detail: 'private server detail' } } });
    openDialog();
    fireEvent.change(screen.getByLabelText('Student school email addresses'), { target: { value: students[0].email } });
    fireEvent.click(screen.getByRole('button', { name: 'Find students' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(dialogText()).not.toContain('private server detail');
    expect(screen.getByRole('button', { name: 'Find students' })).toBeEnabled();
  });

  it('blocks invalid or excessive addresses before requesting account details', () => {
    openDialog();
    const textarea = screen.getByLabelText('Student school email addresses');
    fireEvent.change(textarea, { target: { value: 'not-an-address' } });
    fireEvent.click(screen.getByRole('button', { name: 'Find students' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Enter between 1 and 25 valid school email addresses');
    fireEvent.change(textarea, { target: { value: Array.from({ length: 26 }, (_, index) => `student${index}@henricostudents.org`).join('\n') } });
    fireEvent.click(screen.getByRole('button', { name: 'Find students' }));
    expect(doubles.post).not.toHaveBeenCalled();
  });

  it('prevents duplicate requests and aborts lookup when closed', async () => {
    let resolveRequest;
    doubles.post.mockReturnValueOnce(new Promise((resolve) => { resolveRequest = resolve; }));
    const dialog = openDialog();
    fireEvent.change(screen.getByLabelText('Student school email addresses'), { target: { value: students[0].email } });
    const form = dialog.querySelector('form');
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(doubles.post).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Finding students…' })).toBeDisabled();
    const signal = doubles.post.mock.calls[0][2].signal;
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(signal.aborted).toBe(true);
    await act(async () => { resolveRequest({ data: { students, unmatched_count: 0 } }); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('prevents duplicate code creation and ignores a response after closing', async () => {
    openDialog();
    await findStudents();
    fireEvent.click(screen.getByRole('checkbox', { name: /Alex Rivera/ }));
    let resolveRequest;
    doubles.post.mockReturnValueOnce(new Promise((resolve) => { resolveRequest = resolve; }));
    const createButton = screen.getByRole('button', { name: 'Create verification codes' });
    fireEvent.click(createButton);
    fireEvent.click(createButton);
    expect(doubles.post).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Creating codes…' })).toBeDisabled();
    const signal = doubles.post.mock.calls[1][2].signal;
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(signal.aborted).toBe(true);
    await act(async () => { resolveRequest({ data: { codes } }); });
    expect(screen.queryByDisplayValue('012345')).not.toBeInTheDocument();
  });

  it('allows retry after code creation fails without losing the selection', async () => {
    openDialog();
    await findStudents();
    fireEvent.click(screen.getByRole('checkbox', { name: /Alex Rivera/ }));
    doubles.post.mockRejectedValueOnce({ response: { status: 503 } });
    fireEvent.click(screen.getByRole('button', { name: 'Create verification codes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The request could not be completed. Try again.');
    expect(screen.getByRole('checkbox', { name: /Alex Rivera/ })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Create verification codes' }));
    expect(await screen.findByRole('heading', { name: 'Student verification codes' })).toBeInTheDocument();
  });

  it('hides expired codes and offers a way to create replacements', async () => {
    doubles.post.mockImplementation(async (path) => path.endsWith('/lookup')
      ? { data: { students, unmatched_count: 0 } }
      : { data: { codes: [{ ...codes[0], expires_at: '2000-01-01T00:00:00Z' }] } });
    openDialog();
    await findStudents();
    fireEvent.click(screen.getByRole('checkbox', { name: /Alex Rivera/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Create verification codes' }));
    await screen.findByRole('heading', { name: 'Student verification codes' });
    expect(screen.getByLabelText('Verification code for Alex Rivera')).toHaveValue('Expired');
    expect(screen.getByRole('button', { name: 'Copy code for Alex Rivera' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('This code has expired.');
    fireEvent.click(screen.getByRole('button', { name: 'Find students again' }));
    expect(screen.queryByDisplayValue('Expired')).not.toBeInTheDocument();
  });

  it('traps keyboard focus and closes through the native dialog cancel event', () => {
    const dialog = openDialog();
    const first = screen.getByLabelText('Student school email addresses');
    const last = screen.getByRole('button', { name: 'Close' });
    last.focus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(first).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(last).toHaveFocus();
    fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

function dialogText() {
  return screen.getByRole('dialog').textContent;
}
