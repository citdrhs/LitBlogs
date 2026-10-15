import { useEffect, useRef, useState } from 'react';
import axios from 'axios';

const MAX_STUDENTS = 25;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const requestErrorMessage = (status) => {
  if (status === 400 || status === 422) return 'Enter up to 25 valid student school email addresses.';
  if (status === 401 || status === 403) return 'Your teacher session is no longer available. Sign in again.';
  if (status === 409) return 'The selected accounts changed. Find the students again before creating codes.';
  if (status === 429) return 'Too many requests. Wait a few minutes before trying again.';
  return 'The request could not be completed. Try again.';
};

const studentName = (student) => (
  [student.first_name, student.last_name].filter(Boolean).join(' ') || student.username || 'Student'
);

const TeacherStudentVerificationDialog = ({ darkMode, onClose }) => {
  const dialogRef = useRef(null);
  const emailRef = useRef(null);
  const stageHeadingRef = useRef(null);
  const controllerRef = useRef(null);
  const pendingRef = useRef(false);
  const copyingRef = useRef(false);
  const codeInputsRef = useRef(new Map());
  const [stage, setStage] = useState('input');
  const [emails, setEmails] = useState('');
  const [students, setStudents] = useState([]);
  const [selectedEmails, setSelectedEmails] = useState([]);
  const [unmatchedCount, setUnmatchedCount] = useState(0);
  const [codes, setCodes] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [copyState, setCopyState] = useState(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const dialog = dialogRef.current;
    const invoker = document.activeElement;
    const controller = new AbortController();
    controllerRef.current = controller;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    emailRef.current?.focus();

    return () => {
      controller.abort();
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
      if (invoker?.isConnected) invoker.focus();
    };
  }, []);

  useEffect(() => {
    if (stage !== 'input') stageHeadingRef.current?.focus();
    else emailRef.current?.focus();
  }, [stage]);

  useEffect(() => {
    if (stage !== 'codes') return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [stage]);

  const closeDialog = () => {
    controllerRef.current?.abort();
    setCodes([]);
    onClose();
  };

  const findStudents = async (event) => {
    event.preventDefault();
    if (pendingRef.current) return;
    const requestedEmails = [...new Set(emails.split(/[,;\n\r]+/).map((email) => email.trim().toLowerCase()).filter(Boolean))];
    if (!requestedEmails.length || requestedEmails.length > MAX_STUDENTS
      || requestedEmails.some((email) => email.length > 100 || !EMAIL_PATTERN.test(email))) {
      setError('Enter between 1 and 25 valid school email addresses, separated by commas or new lines.');
      emailRef.current?.focus();
      return;
    }

    const { signal } = controllerRef.current;
    pendingRef.current = true;
    setPending(true);
    setError('');
    try {
      const response = await axios.post('/teacher/student-verifications/lookup', {
        emails: requestedEmails,
      }, { signal });
      if (signal.aborted) return;
      setStudents(response.data.students);
      setSelectedEmails([]);
      setUnmatchedCount(response.data.unmatched_count || 0);
      setStage('selection');
    } catch (requestError) {
      if (!signal.aborted) setError(requestErrorMessage(requestError?.response?.status));
    } finally {
      pendingRef.current = false;
      if (!signal.aborted) setPending(false);
    }
  };

  const createCodes = async () => {
    if (pendingRef.current || !selectedEmails.length) return;
    const { signal } = controllerRef.current;
    pendingRef.current = true;
    setPending(true);
    setError('');
    try {
      const response = await axios.post('/teacher/student-verifications/codes', {
        emails: selectedEmails,
      }, { signal });
      if (signal.aborted) return;
      if (!response.data.codes?.length) {
        setError('No codes were created. Find the students again; their accounts may already be verified.');
        return;
      }
      setCodes(response.data.codes);
      setNow(Date.now());
      setCopyState(null);
      setStage('codes');
    } catch (requestError) {
      if (!signal.aborted) setError(requestErrorMessage(requestError?.response?.status));
    } finally {
      pendingRef.current = false;
      if (!signal.aborted) setPending(false);
    }
  };

  const copyCode = async (entry) => {
    if (copyingRef.current || Date.parse(entry.expires_at) <= Date.now()) return;
    copyingRef.current = true;
    const { signal } = controllerRef.current;
    setCopyState({ email: entry.email, status: 'pending' });
    try {
      await navigator.clipboard.writeText(entry.code);
      if (!signal.aborted) setCopyState({ email: entry.email, status: 'copied' });
    } catch {
      if (!signal.aborted) {
        setCopyState({ email: entry.email, status: 'failed' });
        const input = codeInputsRef.current.get(entry.email);
        input?.focus();
        input?.select();
      }
    } finally {
      copyingRef.current = false;
    }
  };

  const editEmails = () => {
    setStage('input');
    setCodes([]);
    setCopyState(null);
    setError('');
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...dialogRef.current.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled])',
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
  const secondaryClass = 'rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold disabled:opacity-50 dark:border-gray-600';
  const primaryClass = 'rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-cyan-700 dark:hover:bg-cyan-600';

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby="student-verification-title"
      aria-describedby="student-verification-description"
      onKeyDown={handleKeyDown}
      onCancel={(event) => { event.preventDefault(); closeDialog(); }}
      className={`fixed inset-0 m-auto max-h-[90vh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-2xl p-6 shadow-xl backdrop:bg-black/60 ${
        darkMode ? 'bg-gray-800 text-gray-100' : 'bg-white text-gray-900'
      }`}
    >
      <p className="text-xs font-bold uppercase tracking-wider text-blue-700 dark:text-cyan-300">Teacher assistance</p>
      <h2 id="student-verification-title" className="mt-2 text-2xl font-semibold">Verify students</h2>
      <p id="student-verification-description" className="mt-3 text-sm leading-6 text-gray-600 dark:text-gray-300">
        Help students who cannot receive their verification email. Confirm each student’s identity in person before sharing their private code.
      </p>

      {stage === 'input' && (
        <form id="student-verification-lookup" onSubmit={findStudents} aria-busy={pending} className="mt-6">
          <label htmlFor="student-verification-emails" className="block text-sm font-semibold">Student school email addresses</label>
          <p id="student-verification-email-help" className="mt-2 text-sm text-gray-600 dark:text-gray-300">
            Paste up to 25 exact addresses, separated by commas, semicolons, or new lines. Only eligible unverified student accounts will appear.
          </p>
          <textarea
            ref={emailRef}
            id="student-verification-emails"
            aria-describedby="student-verification-email-help"
            value={emails}
            onChange={(event) => setEmails(event.target.value)}
            rows={5}
            maxLength={6500}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            required
            disabled={pending}
            className={`${fieldClass} disabled:opacity-60`}
          />
        </form>
      )}

      {stage === 'selection' && (
        <section className="mt-6" aria-busy={pending}>
          <h3 ref={stageHeadingRef} tabIndex={-1} className="text-lg font-semibold outline-none">Select students to help</h3>
          {students.length > 0 ? (
            <>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">Select the students whose identities you have confirmed.</p>
              <div className="mt-4 space-y-2">
                {students.map((student) => (
                  <label key={student.id} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 ${darkMode ? 'border-gray-600' : 'border-gray-200'}`}>
                    <input
                      type="checkbox"
                      checked={selectedEmails.includes(student.email)}
                      onChange={(event) => setSelectedEmails((selected) => event.target.checked
                        ? [...selected, student.email]
                        : selected.filter((email) => email !== student.email))}
                      disabled={pending}
                      className="mt-1 h-4 w-4 rounded border-gray-400 text-blue-700 focus:ring-blue-500"
                      aria-label={`Verify ${studentName(student)} (${student.email})`}
                    />
                    <span className="min-w-0">
                      <span className="block font-semibold">{studentName(student)}</span>
                      <span className="block break-all text-sm text-gray-600 dark:text-gray-300">{student.email}</span>
                      <span className="mt-2 inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900 dark:bg-amber-950 dark:text-amber-200">Awaiting verification</span>
                    </span>
                  </label>
                ))}
              </div>
              <p role="status" className="mt-3 text-sm font-medium">{selectedEmails.length} of {students.length} selected</p>
            </>
          ) : (
            <p role="status" className="mt-3 rounded-xl bg-gray-100 p-4 text-sm leading-6 dark:bg-gray-700">
              No eligible unverified student accounts were found. Check the exact addresses and ask students to complete registration. Accounts already verified will not appear.
            </p>
          )}
          {unmatchedCount > 0 && students.length > 0 && (
            <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">
              Some addresses did not match an eligible unverified student account. Check the spelling or ask whether they have already verified.
            </p>
          )}
        </section>
      )}

      {stage === 'codes' && (
        <section className="mt-6">
          <h3 ref={stageHeadingRef} tabIndex={-1} className="text-lg font-semibold outline-none">Student verification codes</h3>
          <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
            Tell each code to its student in person. No email is sent. The student signs in with their school email and password, then chooses “Enter a teacher code” on the verification page. Each code works once for 15 minutes and only for the email shown with it.
          </p>
          <div className="mt-4 space-y-4">
            {codes.map((entry) => {
              const expiresAt = Date.parse(entry.expires_at);
              const expired = !Number.isFinite(expiresAt) || expiresAt <= now;
              const remaining = Math.max(0, Math.ceil((expiresAt - now) / 1000));
              const countdown = `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`;
              const entryCopyState = copyState?.email === entry.email ? copyState.status : null;
              return (
                <article key={entry.student_id} className={`rounded-xl border p-4 ${darkMode ? 'border-gray-600' : 'border-gray-200'}`}>
                  <h4 className="font-semibold">{studentName(entry)}</h4>
                  <p className="mt-1 break-all text-sm text-gray-600 dark:text-gray-300">{entry.email}</p>
                  <label htmlFor={`student-code-${entry.student_id}`} className="mt-4 block text-sm font-medium">Verification code for {studentName(entry)}</label>
                  <div className="flex flex-wrap items-center gap-3">
                    <input
                      ref={(input) => { if (input) codeInputsRef.current.set(entry.email, input); else codeInputsRef.current.delete(entry.email); }}
                      id={`student-code-${entry.student_id}`}
                      readOnly
                      autoComplete="off"
                      spellCheck={false}
                      value={expired ? 'Expired' : entry.code}
                      onFocus={(event) => event.target.select()}
                      className={`mt-2 w-full max-w-48 rounded-lg border px-3 py-2 font-mono text-2xl font-bold tracking-[0.15em] ${darkMode ? 'border-gray-600 bg-gray-700 text-gray-100' : 'border-gray-300 bg-white text-gray-900'}`}
                    />
                    <button type="button" onClick={() => copyCode(entry)} disabled={expired || copyState?.status === 'pending'} className={`${secondaryClass} mt-2`} aria-label={`Copy code for ${studentName(entry)}`}>
                      {entryCopyState === 'pending' ? 'Copying…' : 'Copy code'}
                    </button>
                  </div>
                  {expired ? (
                    <p role="status" className="mt-3 text-sm font-semibold text-amber-800 dark:text-amber-200">This code has expired. Find the student again to create a new one.</p>
                  ) : (
                    <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">Expires in {countdown} · <time dateTime={entry.expires_at}>{new Date(entry.expires_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></p>
                  )}
                  {entryCopyState === 'copied' && !expired && <p role="status" className="mt-2 text-sm text-emerald-700 dark:text-emerald-300">Code copied.</p>}
                  {entryCopyState === 'failed' && !expired && <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">Copy failed. Select and copy the code above.</p>}
                </article>
              );
            })}
          </div>
          <p className="mt-4 text-sm font-medium">Codes are shown only here. Closing this window clears them from this screen. Creating a new code replaces the previous one.</p>
        </section>
      )}

      {error && <p role="alert" className="mt-4 rounded-lg bg-red-100 px-4 py-3 text-sm text-red-900 dark:bg-red-950 dark:text-red-200">{error}</p>}
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        {stage === 'input' && <button type="submit" form="student-verification-lookup" disabled={pending} className={primaryClass}>{pending ? 'Finding students…' : 'Find students'}</button>}
        {stage === 'selection' && (
          <>
            <button type="button" onClick={editEmails} disabled={pending} className={secondaryClass}>Edit addresses</button>
            {students.length > 0 && <button type="button" onClick={createCodes} disabled={pending || !selectedEmails.length} className={primaryClass}>{pending ? 'Creating codes…' : 'Create verification codes'}</button>}
          </>
        )}
        {stage === 'codes' && <button type="button" onClick={editEmails} className={secondaryClass}>Find students again</button>}
        <button type="button" onClick={closeDialog} className={secondaryClass}>Close</button>
      </div>
    </dialog>
  );
};

export default TeacherStudentVerificationDialog;
