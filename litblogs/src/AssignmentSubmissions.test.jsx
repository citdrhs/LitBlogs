// @vitest-environment jsdom

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';

import AssignmentSubmissions from './AssignmentSubmissions.jsx';

const mocks = vi.hoisted(() => ({ axios: { get: vi.fn() } }));
vi.mock('axios', () => ({ default: mocks.axios }));
vi.mock('./components/Navbar', () => ({ default: () => null }));
vi.mock('./components/Footer', () => ({ default: () => null }));
vi.mock('./components/Loader', () => ({ default: () => <p>Loading</p> }));

const IMAGE_URL = `/api/uploads/objects/ab/${'ab'.repeat(16)}.png`;

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  localStorage.clear();
  mocks.axios.get.mockImplementation(async (url) => {
    if (url === '/classes/4/assignments?include_archived=true') {
      return { data: [{ id: 12, title: 'Archived reading response', description: 'Chapter four' }] };
    }
    if (url === '/classes/4/assignments/12/submissions') {
      return { data: [
        {
          id: 31,
          content: `<p>Illustrated answer</p><img src="${IMAGE_URL}" alt="Student diagram">`,
          content_format: 'rich',
          submitted_at: '2026-10-06T14:00:00Z',
          student: { first_name: 'Test', last_name: 'Student' },
          replies: [],
        },
        {
          id: 32,
          content: 'Literal <img src="https://elsewhere.invalid/pixel"> text',
          content_format: 'plain',
          submitted_at: '2026-10-06T14:01:00Z',
          student: { first_name: 'Legacy', last_name: 'Student' },
          replies: [],
        },
      ] };
    }
    throw new Error(`Unexpected GET ${url}`);
  });
});

it('shows an authorized submitted image while viewing an archived assignment', async () => {
  render(
    <MemoryRouter initialEntries={['/class/4/assignment/12/submissions']}>
      <Routes>
        <Route path="/class/:classId/assignment/:assignmentId/submissions" element={<AssignmentSubmissions />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText('Archived reading response')).toBeInTheDocument();
  expect(mocks.axios.get).toHaveBeenCalledWith('/classes/4/assignments?include_archived=true');
  expect(screen.getByRole('img', { name: 'Student diagram' }))
    .toHaveAttribute('src', IMAGE_URL);
  expect(screen.getByText('Illustrated answer')).toBeInTheDocument();
  expect(screen.getByText('Literal <img src="https://elsewhere.invalid/pixel"> text'))
    .toBeInTheDocument();
  expect(screen.getAllByRole('img')).toHaveLength(1);
});

it('returns to the teacher assignment controls after viewing archived submissions', async () => {
  const ReturnState = () => {
    const location = useLocation();
    return <p>{`${location.state?.selectedClass?.id}:${location.state?.classDetailsTab}`}</p>;
  };

  render(
    <MemoryRouter initialEntries={[{
      pathname: '/class/4/assignment/12/submissions',
      state: { selectedClass: { id: 4, name: 'Reading' }, classDetailsTab: 'Assignments' },
    }]}>
      <Routes>
        <Route path="/class/:classId/assignment/:assignmentId/submissions" element={<AssignmentSubmissions />} />
        <Route path="/teacher-dashboard" element={<ReturnState />} />
      </Routes>
    </MemoryRouter>,
  );

  fireEvent.click(await screen.findByRole('button', { name: 'Back to Class' }));
  expect(screen.getByText('4:Assignments')).toBeInTheDocument();
});
