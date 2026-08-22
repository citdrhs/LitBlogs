// @vitest-environment jsdom

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';

import ClassDetails from './ClassDetails';

const mocks = vi.hoisted(() => ({
  axios: {
    get: vi.fn(),
  },
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
  mocks.axios.get.mockImplementation(async (url) => {
    if (url === '/classes/4/details') {
      return { data: { id: 4, name: 'Literature', access_code: 'READ42' } };
    }
    if (url === '/classes/4/students') return { data: [] };
    if (url === '/classes/4/posts') return { data: [] };
    if (url === '/classes/4/assignments') {
      return {
        data: [{
          id: 12,
          title: 'Close reading',
          description: 'Read chapter four',
          due_date: '2099-08-22T12:00:00Z',
          allow_late: true,
          visibility: 'class',
          stats: {},
        }],
      };
    }
    if (url === '/classes/4/analytics') return { data: {} };
    throw new Error(`Unexpected GET ${url}`);
  });
});

it('describes class visibility as assignment audience rather than peer submission access', async () => {
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

  expect(await screen.findByText('Visible to Students')).toBeInTheDocument();
  expect(screen.queryByText('Public Submissions')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Create Assignment' }));
  expect(screen.getByText('Assignment Audience')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Visible to Students' })).toBeInTheDocument();
});
