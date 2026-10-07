// @vitest-environment jsdom

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';

import ClassDetails from './ClassDetails';

const mocks = vi.hoisted(() => ({
  axios: { get: vi.fn(), delete: vi.fn(), post: vi.fn() },
}));

vi.mock('axios', () => ({ default: mocks.axios }));
vi.mock('./Loader', () => ({ default: () => <p>Loading class</p> }));
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, initial: _initial, animate: _animate, ...props }) => (
      <div {...props}>{children}</div>
    ),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
});

it('hides an assignment with confirmation and lets its teacher restore it', async () => {
  let archivedAt = null;
  mocks.axios.get.mockImplementation(async (url) => {
    if (url === '/classes/4/details') {
      return { data: { id: 4, name: 'Literature', access_code: 'READ42' } };
    }
    if (url === '/classes/4/students' || url === '/classes/4/posts') return { data: [] };
    if (url === '/classes/4/assignments?include_archived=true'
      || url === '/classes/4/assignments') {
      return { data: [{
        id: 12,
        title: 'Close reading',
        description: 'Read chapter four',
        due_date: '2099-08-22T12:00:00Z',
        allow_late: true,
        visibility: 'class',
        archived_at: archivedAt,
        stats: {},
      }] };
    }
    if (url === '/classes/4/analytics') return { data: {} };
    throw new Error(`Unexpected GET ${url}`);
  });
  mocks.axios.delete.mockImplementation(async () => {
    archivedAt = '2026-10-06T12:00:00Z';
    return { data: { id: 12, archived_at: archivedAt } };
  });
  mocks.axios.post.mockImplementation(async () => {
    archivedAt = null;
    return { data: { id: 12, archived_at: null } };
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);

  render(
    <MemoryRouter>
      <ClassDetails
        classData={{ id: 4, name: 'Literature', access_code: 'READ42' }}
        darkMode={false}
        onBack={() => undefined}
        initialTab="Assignments"
      />
    </MemoryRouter>,
  );

  fireEvent.click(await screen.findByRole('button', { name: 'Hide Assignment' }));
  expect(mocks.axios.get).toHaveBeenCalledWith('/classes/4/assignments?include_archived=true');
  await waitFor(() => expect(mocks.axios.delete).toHaveBeenCalledWith(
    '/classes/4/assignments/12',
  ));
  expect(confirm).toHaveBeenCalled();
  expect(await screen.findByText('Archived Assignments')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Restore Assignment' }));
  await waitFor(() => expect(mocks.axios.post).toHaveBeenCalledWith(
    '/classes/4/assignments/12/restore',
  ));
  expect(await screen.findByRole('button', { name: 'Hide Assignment' })).toBeInTheDocument();
  confirm.mockRestore();
});
