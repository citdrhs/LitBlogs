import { useEffect, useRef, useState } from 'react';
import axios from 'axios';

const actionError = (status, action, retryAfter) => {
  const deleting = action === 'delete';
  if (status === 401 || status === 403) return 'You need an active administrator session. Sign in again.';
  if (status === 404) return 'This account is no longer available. Refresh the dashboard.';
  if (status === 429 && action === 'recovery') {
    const seconds = Number(retryAfter);
    if (Number.isFinite(seconds) && seconds > 0 && seconds <= 86400) {
      const minutes = Math.ceil(seconds / 60);
      return `A recovery email was requested recently. Try again in ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}.`;
    }
    return 'A recovery email was requested recently. Wait a few minutes before trying again.';
  }
  if (status === 409) {
    if (action === 'verification') return 'Verification links require an active account with an unverified email. Refresh the dashboard and try again.';
    return deleting
      ? 'This account is protected or still has classes, schoolwork, or uploads. Disable it while those records are preserved or transferred.'
      : 'Recovery requires an active account with a verified email. If the account changed just now, refresh and try again.';
  }
  if (deleting && (status === 400 || status === 422)) return 'Type the account email exactly to confirm deletion.';
  if (action === 'verification') return 'The verification link could not be created. Try again.';
  return deleting ? 'The account could not be deleted. Try again.' : 'Recovery could not be requested. Try again.';
};

const AdminAccountActionDialog = ({ user, action, darkMode, onClose, onDeleted }) => {
  const deleting = action === 'delete';
  const verifying = action === 'verification';
  const dialogRef = useRef(null);
  const initialFocusRef = useRef(null);
  const resultLinkRef = useRef(null);
  const queuedMessageRef = useRef(null);
  const controllerRef = useRef(null);
  const requestPendingRef = useRef(false);
  const [confirmation, setConfirmation] = useState('');
  const [delivery, setDelivery] = useState('manual');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [copyState, setCopyState] = useState('idle');

  useEffect(() => {
    const dialog = dialogRef.current;
    const invoker = document.activeElement;
    const controller = new AbortController();
    controllerRef.current = controller;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    initialFocusRef.current?.focus();

    return () => {
      controller.abort();
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
      if (invoker?.isConnected) invoker.focus();
      else document.getElementById('admin-user-search')?.focus();
    };
  }, []);

  useEffect(() => {
    if (result?.reset_url || result?.verification_url) {
      resultLinkRef.current?.focus();
      resultLinkRef.current?.select();
    } else if (result?.queued) {
      queuedMessageRef.current?.focus();
    }
  }, [result]);

  useEffect(() => {
    if (copyState === 'failed') {
      resultLinkRef.current?.focus();
      resultLinkRef.current?.select();
    }
  }, [copyState]);

  const requestClose = () => {
    if (!requestPendingRef.current) onClose();
  };

  const submitAction = async (event) => {
    event.preventDefault();
    if (requestPendingRef.current || (deleting && confirmation !== user.email)) return;
    const { signal } = controllerRef.current;
    requestPendingRef.current = true;
    setPending(true);
    setError('');
    try {
      if (deleting) {
        await axios.delete(`/admin/users/${user.id}`, { params: { confirm: confirmation }, signal });
        if (!signal.aborted) onDeleted(user);
      } else {
        const response = await axios.post(`/admin/users/${user.id}/${verifying ? 'verification' : 'recovery'}`, verifying ? {} : { delivery }, { signal });
        if (!signal.aborted) setResult(response.data);
      }
    } catch (requestError) {
      if (!signal.aborted) setError(actionError(requestError?.response?.status, action, requestError?.response?.headers?.['retry-after']));
    } finally {
      requestPendingRef.current = false;
      if (!signal.aborted) setPending(false);
    }
  };

  const copyLink = async () => {
    if (copyState === 'pending') return;
    const { signal } = controllerRef.current;
    setCopyState('pending');
    try {
      await navigator.clipboard.writeText(verifying ? result.verification_url : result.reset_url);
      if (!signal.aborted) setCopyState('copied');
    } catch {
      if (!signal.aborted) setCopyState('failed');
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      requestClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...dialogRef.current.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled])')];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first) {
      event.preventDefault();
      dialogRef.current.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const fieldClass = `mt-2 w-full rounded-lg border px-3 py-2 text-sm ${
    darkMode ? 'border-gray-600 bg-gray-700 text-gray-100' : 'border-gray-300 bg-white text-gray-900'
  }`;
  const expiry = result?.expires_at
    ? new Date(result.expires_at).toLocaleString(undefined, { timeZoneName: 'short' })
    : '';
  const resultLink = verifying ? result?.verification_url : result?.reset_url;
  const linkLabel = verifying ? 'Verification link' : 'Recovery link';
  const submitLabel = deleting
    ? (pending ? 'Deleting account…' : 'Permanently delete account')
    : verifying
      ? (pending ? 'Creating verification link…' : 'Create verification link')
      : (pending ? 'Requesting recovery…' : delivery === 'manual' ? 'Create recovery link' : 'Send recovery email');

  return (
    <dialog
      ref={dialogRef}
      tabIndex={-1}
      aria-modal="true"
      aria-labelledby="admin-account-action-title"
      aria-describedby="admin-account-action-description"
      onKeyDown={handleKeyDown}
      onCancel={(event) => { event.preventDefault(); requestClose(); }}
      className={`fixed inset-0 m-auto max-h-[90vh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl p-6 shadow-xl backdrop:bg-black/60 ${
        darkMode ? 'bg-gray-800 text-gray-100' : 'bg-white text-gray-900'
      }`}
    >
      <h2 id="admin-account-action-title" className="text-xl font-semibold">
        {deleting ? 'Delete account' : verifying ? 'Create verification link' : 'Recover access'} for {user.username}
      </h2>
      <p className="mt-2 break-words text-sm font-medium">{user.email}</p>
      <p id="admin-account-action-description" className={`mt-3 text-sm ${darkMode ? 'text-gray-300' : 'text-gray-600'}`}>
        {deleting
          ? 'Deleting this account permanently removes its profile and authentication data. This cannot be undone.'
          : verifying
            ? 'Help this user verify their email and finish setting up access.'
            : 'Help this user choose a new password with a recovery link.'}
      </p>
      <form id="admin-account-action-form" onSubmit={submitAction} className="mt-5 space-y-4">
        {deleting ? (
          <>
            <p className="rounded-lg bg-red-100 px-3 py-3 text-sm text-red-900">
              Accounts with classes, schoolwork, or uploads cannot be deleted until those records are preserved or transferred. Disable the account while resolving them.
            </p>
            <div>
              <label htmlFor="admin-delete-confirmation" className="block break-words text-sm font-medium">Type {user.email} to confirm</label>
              <input
                ref={initialFocusRef}
                id="admin-delete-confirmation"
                type="text"
                autoComplete="off"
                spellCheck={false}
                maxLength={100}
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                disabled={pending}
                className={fieldClass}
              />
            </div>
          </>
        ) : resultLink ? (
          <>
            <p className="text-sm">Share this link privately with the user. No email has been sent.</p>
            <div>
              <label htmlFor="admin-account-link" className="block text-sm font-medium">{linkLabel}</label>
              <textarea
                ref={resultLinkRef}
                id="admin-account-link"
                readOnly
                autoComplete="off"
                spellCheck={false}
                rows={3}
                value={resultLink}
                className={fieldClass}
              />
            </div>
            <p className="text-sm">Expires: <time dateTime={result.expires_at}>{expiry}</time></p>
            <p className="text-sm">Copy the link before closing. It is only shown here once.</p>
            {verifying && <p className="text-sm">This verification link can be used once, before it expires.</p>}
            {copyState === 'copied' && <p role="status" className="text-sm text-emerald-700 dark:text-emerald-300">{linkLabel} copied.</p>}
            {copyState === 'failed' && <p role="alert" className="text-sm text-red-700 dark:text-red-300">Copy failed. Select and copy the {linkLabel.toLowerCase()} above.</p>}
          </>
        ) : result?.queued ? (
          <p ref={queuedMessageRef} tabIndex={-1} role="status" className="rounded-lg bg-emerald-100 px-3 py-3 text-sm text-emerald-900">
            Recovery email queued for {result.email}. Delivery may take a few minutes.
          </p>
        ) : verifying ? (
          <p className="text-sm">You will receive a private link to share with this user. No email will be sent.</p>
        ) : (
          <fieldset disabled={pending} className="space-y-3">
            <legend className="mb-3 text-sm font-medium">How should the user receive the link?</legend>
            <label className="flex items-center gap-2 text-sm">
              <input ref={initialFocusRef} type="radio" name="recovery-delivery" value="manual" checked={delivery === 'manual'} onChange={() => setDelivery('manual')} />
              Share a recovery link myself
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name="recovery-delivery" value="email" checked={delivery === 'email'} onChange={() => setDelivery('email')} />
              Email a recovery link to this user
            </label>
          </fieldset>
        )}
        {error && <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900">{error}</p>}
      </form>
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        {resultLink && (
          <button type="button" onClick={copyLink} disabled={copyState === 'pending'} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
            {copyState === 'pending' ? 'Copying…' : `Copy ${linkLabel.toLowerCase()}`}
          </button>
        )}
        {!result && (
          <button
            ref={verifying ? initialFocusRef : undefined}
            type="submit"
            form="admin-account-action-form"
            disabled={pending || (deleting && confirmation !== user.email)}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 ${deleting ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'}`}
          >
            {submitLabel}
          </button>
        )}
        <button type="button" onClick={requestClose} disabled={pending} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold disabled:opacity-50">
          {deleting ? 'Cancel' : 'Close'}
        </button>
      </div>
    </dialog>
  );
};

export default AdminAccountActionDialog;
