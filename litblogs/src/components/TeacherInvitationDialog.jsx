import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { assetPath } from '../utils/urlUtils';

const invitationError = (status) => {
  if (status === 400 || status === 422) return 'Enter an email address from an approved school domain.';
  if (status === 409) return 'An invitation could not be created for this email. Check whether an account already exists.';
  if (status === 401 || status === 403) return 'You need an active administrator session to create invitations. Sign in again.';
  return 'The invitation could not be created. Try again.';
};

const TeacherInvitationDialog = ({ darkMode, onClose }) => {
  const dialogRef = useRef(null);
  const emailRef = useRef(null);
  const codeRef = useRef(null);
  const manualCopyRef = useRef(null);
  const controllerRef = useRef(null);
  const requestPendingRef = useRef(false);
  const [email, setEmail] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [invitation, setInvitation] = useState(null);
  const [copyState, setCopyState] = useState('idle');

  useEffect(() => {
    const dialog = dialogRef.current;
    const invoker = document.activeElement;
    const controller = new AbortController();
    controllerRef.current = controller;
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    emailRef.current?.focus();

    return () => {
      controller.abort();
      if (typeof dialog.close === 'function') {
        dialog.close();
      } else {
        dialog.removeAttribute('open');
      }
      if (invoker?.isConnected) invoker.focus();
    };
  }, []);

  useEffect(() => {
    if (invitation) codeRef.current?.focus();
  }, [invitation]);

  useEffect(() => {
    if (copyState === 'failed') {
      manualCopyRef.current?.focus();
      manualCopyRef.current?.select();
    }
  }, [copyState]);

  const createInvitation = async (event) => {
    event.preventDefault();
    if (requestPendingRef.current) return;
    const teacherEmail = email.trim();
    if (!teacherEmail) {
      setError('Enter the teacher’s school email address.');
      emailRef.current?.focus();
      return;
    }

    const { signal } = controllerRef.current;
    requestPendingRef.current = true;
    setPending(true);
    setError('');
    try {
      const response = await axios.post('/admin/teacher-invitations', {
        email: teacherEmail,
      }, { signal });
      if (!signal.aborted) setInvitation(response.data);
    } catch (requestError) {
      if (!signal.aborted) setError(invitationError(requestError?.response?.status));
    } finally {
      requestPendingRef.current = false;
      if (!signal.aborted) setPending(false);
    }
  };

  const signupUrl = new URL(assetPath('sign-up'), window.location.origin).href;
  const expiry = invitation
    ? new Date(invitation.expires_at).toLocaleString(undefined, { timeZoneName: 'short' })
    : '';
  const invitationText = invitation ? [
    'You are invited to join LitBlogs as a teacher.',
    `Sign up: ${signupUrl}`,
    `Email: ${invitation.email}`,
    `Teacher invitation token: ${invitation.invitation_token}`,
    `Expires: ${expiry}`,
    'Choose Teacher, enter this code in the Teacher invitation token field, and verify your email to finish signing up.',
    'This code works once and only with the email address above.',
  ].join('\n') : '';

  const copyInvitation = async () => {
    if (copyState === 'pending') return;
    const { signal } = controllerRef.current;
    setCopyState('pending');
    try {
      await navigator.clipboard.writeText(invitationText);
      if (!signal.aborted) setCopyState('copied');
    } catch {
      if (!signal.aborted) setCopyState('failed');
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...dialogRef.current.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled])',
    )];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  };

  const fieldClass = `mt-2 w-full rounded-lg border px-3 py-2 text-sm ${
    darkMode ? 'border-gray-600 bg-gray-700 text-gray-100' : 'border-gray-300 bg-white text-gray-900'
  }`;

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby="teacher-invitation-title"
      aria-describedby="teacher-invitation-description"
      onKeyDown={handleKeyDown}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className={`fixed inset-0 m-auto max-h-[90vh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl p-6 shadow-xl backdrop:bg-black/60 ${
        darkMode ? 'bg-gray-800 text-gray-100' : 'bg-white text-gray-900'
      }`}
    >
      <h2 id="teacher-invitation-title" className="text-xl font-semibold">Invite Teacher</h2>
      <p id="teacher-invitation-description" className={`mt-3 text-sm ${darkMode ? 'text-gray-300' : 'text-gray-600'}`}>
        {invitation
          ? 'Share this invitation privately with the teacher. No email has been sent.'
          : 'Create a code for the teacher’s school email. It works once and expires after 48 hours.'}
      </p>

      {invitation ? (
        <div className="mt-5 space-y-4">
          <p className="break-words text-sm font-medium">{invitation.email}</p>
          <div>
            <label htmlFor="teacher-invitation-code" className="block text-sm font-medium">Invitation code</label>
            <input
              ref={codeRef}
              id="teacher-invitation-code"
              readOnly
              autoComplete="off"
              spellCheck={false}
              value={invitation.invitation_token}
              onFocus={(event) => event.target.select()}
              className={`${fieldClass} font-mono`}
            />
          </div>
          <p className="text-sm">Expires: <time dateTime={invitation.expires_at}>{expiry}</time></p>
          <p className="text-sm">
            <a href={signupUrl} target="_blank" rel="noopener noreferrer" className="font-semibold text-blue-600 underline dark:text-blue-300">Sign up</a>
            {' '}with this email, choose Teacher, enter the code in the Teacher invitation token field, and verify your email.
          </p>
          <p className={`text-sm ${darkMode ? 'text-gray-300' : 'text-gray-600'}`}>
            Copy this invitation before closing. The code is only shown here once.
          </p>
          {copyState === 'copied' && <p role="status" className="text-sm text-emerald-700 dark:text-emerald-300">Invitation copied.</p>}
          {copyState === 'failed' && (
            <div>
              <p role="alert" className="mb-3 text-sm text-red-700 dark:text-red-300">Copy failed. Select and copy the invitation below.</p>
              <label htmlFor="teacher-invitation-manual-copy" className="block text-sm font-medium">Invitation to copy manually</label>
              <textarea
                ref={manualCopyRef}
                id="teacher-invitation-manual-copy"
                readOnly
                autoComplete="off"
                spellCheck={false}
                rows={8}
                value={invitationText}
                className={fieldClass}
              />
            </div>
          )}
        </div>
      ) : (
        <form id="teacher-invitation-form" onSubmit={createInvitation} className="mt-5">
          <label htmlFor="teacher-invitation-email" className="block text-sm font-medium">Teacher email</label>
          <input
            ref={emailRef}
            id="teacher-invitation-email"
            type="email"
            required
            maxLength={100}
            autoComplete="off"
            value={email}
            disabled={pending}
            onChange={(event) => setEmail(event.target.value)}
            className={`${fieldClass} disabled:opacity-60`}
          />
          <p className={`mt-3 text-sm ${darkMode ? 'text-gray-300' : 'text-gray-600'}`}>
            Creating a code replaces any previous unused invitation for this email.
          </p>
          {error && <p role="alert" className="mt-3 rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">{error}</p>}
        </form>
      )}
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        {invitation ? (
          <button
            type="button"
            onClick={copyInvitation}
            disabled={copyState === 'pending'}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {copyState === 'pending' ? 'Copying…' : 'Copy invitation'}
          </button>
        ) : (
          <button
            type="submit"
            form="teacher-invitation-form"
            disabled={pending}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {pending ? 'Creating invitation…' : 'Create invitation'}
          </button>
        )}
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold"
        >
          Close
        </button>
      </div>
    </dialog>
  );
};

export default TeacherInvitationDialog;
