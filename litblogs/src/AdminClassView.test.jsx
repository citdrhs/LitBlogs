// @vitest-environment jsdom

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  axios: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

vi.mock('axios', () => ({ default: mocks.axios }));
vi.mock('./components/Navbar', () => ({ default: () => null }));
vi.mock('./components/Footer', () => ({ default: () => null }));
vi.mock('./components/Loader', () => ({ default: () => <p>Loading</p> }));
vi.mock('./components/LitBlogsEditor', () => ({
  default: ({ value, onChange }) => (
    <textarea
      aria-label="Post content"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

import AdminDashboard from './AdminDashboard';
import AssignmentSubmissions from './AssignmentSubmissions';
import PostView from './PostView';
import StudentDetails from './components/StudentDetails';

const selectedClass = { id: 4, name: 'Alpha Literature', status: 'active' };
const assignment = {
  id: 12,
  title: 'Archived reading response',
  description: 'Chapter four',
  due_date: '2099-08-22T12:00:00Z',
  allow_late: true,
  visibility: 'private',
  archived_at: '2026-10-06T12:00:00Z',
  stats: { submitted: 1 },
};

const LocationProbe = () => {
  const location = useLocation();
  return (
    <output data-testid="location-state">
      {JSON.stringify({
        pathname: location.pathname,
        selectedClass: location.state?.selectedClass,
        classDetailsTab: location.state?.classDetailsTab,
      })}
    </output>
  );
};

const renderRoutes = () => render(
  <MemoryRouter initialEntries={['/admin-dashboard']}>
    <LocationProbe />
    <Routes>
      <Route path="/admin-dashboard" element={<AdminDashboard />} />
      <Route path="/class/:classId/post/:postId" element={<PostView />} />
      <Route
        path="/class/:classId/assignment/:assignmentId/submissions"
        element={<AssignmentSubmissions />}
      />
      <Route
        path="/class/:classId/student/:studentId"
        element={<StudentDetails darkMode={false} />}
      />
    </Routes>
  </MemoryRouter>,
);

const renderTeacherPost = () => render(
  <MemoryRouter initialEntries={[{
    pathname: '/class/4/post/7',
    state: { postViewerContext: { selectedClass, classDetailsTab: 'Blogs' } },
  }]}>
    <LocationProbe />
    <Routes>
      <Route path="/class/:classId/post/:postId" element={<PostView />} />
      <Route path="/teacher-dashboard" element={<p>Teacher dashboard</p>} />
    </Routes>
  </MemoryRouter>,
);

const openSelectedClass = async (tab) => {
  fireEvent.click(await screen.findByRole('button', { name: 'View class data for Alpha Literature' }));
  if (tab) fireEvent.click(screen.getByRole('button', { name: tab }));
};

const expectAdminClassReturn = async (tab) => {
  await waitFor(() => {
    const state = JSON.parse(screen.getByTestId('location-state').textContent);
    expect(state).toMatchObject({
      pathname: '/admin-dashboard',
      selectedClass: { id: selectedClass.id },
      classDetailsTab: tab,
    });
  });
  expect(screen.getByRole('button', { name: tab })).toHaveClass('text-blue-500');
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  sessionStorage.setItem('user_info', JSON.stringify({
    userId: 1,
    username: 'admin-user',
    role: 'ADMIN',
    is_admin: true,
  }));
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({ matches: false }),
  });
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);

  mocks.axios.get.mockImplementation(async (path, config) => {
    if (path === '/users') return { data: [] };
    if (path === '/classes' && config?.params?.status === 'archived') return { data: [] };
    if (path === '/classes') return { data: [selectedClass] };
    if (path === '/classes/4/details') {
      return { data: { ...selectedClass, description: 'Class overview', enrollment_count: 1 } };
    }
    if (path === '/classes/4/students') {
      return { data: [{
        id: 9,
        username: 'student-a',
        first_name: 'Student',
        last_name: 'Alpha',
        email: 'student-a@example.test',
        created_at: '2026-10-01T00:00:00Z',
      }] };
    }
    if (path === '/classes/4/posts') {
      return { data: [{
        id: 7,
        title: 'Alpha post',
        content: '<p>Post content</p>',
        created_at: '2026-10-01T00:00:00Z',
        author: 'Student Alpha',
        likes: 1,
        comments: 1,
      }] };
    }
    if (path === '/classes/4/assignments?include_archived=true') {
      return { data: [assignment] };
    }
    if (path === '/classes/4/analytics') return { data: {} };
    if (path === '/classes/4/posts/7') {
      return { data: {
        id: 7,
        title: 'Alpha post',
        content: '<p>Post content</p>',
        created_at: '2026-10-01T00:00:00Z',
        owner_id: 9,
        author: { first_name: 'Student', last_name: 'Alpha' },
        likes: 1,
        is_saved: false,
      } };
    }
    if (path === '/classes/4/posts/7/likes') {
      return { data: { user_liked: false, like_count: 1 } };
    }
    if (path.startsWith('/classes/4/posts/7/comments?')) {
      return { data: {
        comments: [{
          id: 21,
          content: 'Synthetic class comment',
          created_at: '2026-10-02T00:00:00Z',
          likes: 2,
          user_liked: false,
          replies: [],
          reply_count: 0,
          has_more_replies: false,
          user: { first_name: 'Student', last_name: 'Beta', username: 'student-b' },
        }],
        total: 1,
        has_more: false,
      } };
    }
    if (path === '/classes/4/assignments/12/submissions') {
      return { data: [{
        id: 31,
        content: 'Synthetic archived submission',
        content_format: 'plain',
        submitted_at: '2026-10-06T14:00:00Z',
        student: { first_name: 'Student', last_name: 'Alpha' },
        replies: [{
          id: 32,
          content: 'Synthetic teacher feedback',
          created_at: '2026-10-06T14:10:00Z',
          user: { first_name: 'Teacher', last_name: 'Alpha' },
        }],
      }] };
    }
    if (path === '/classes/4/students/9') {
      return { data: {
        id: 9,
        username: 'student-a',
        email: 'student-a@example.test',
        first_name: 'Student',
        last_name: 'Alpha',
        enrollment_date: '2026-10-01T00:00:00Z',
        teacher_notes: 'Synthetic teacher note',
        recent_activity: [],
      } };
    }
    if (path === '/classes/4/students/9/posts') return { data: [] };
    throw new Error(`Unexpected GET ${path}`);
  });
});

describe('administrator read-only class view journeys', () => {
  it('returns from a class post to the selected class and Blogs tab', async () => {
    renderRoutes();
    await openSelectedClass('Blogs');
    fireEvent.click(await screen.findByText('Alpha post'));

    expect(await screen.findByText('Post content')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Like/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Save/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit Post' })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText('Add a comment...')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show comments' }));
    expect(await screen.findByText('Synthetic class comment')).toBeInTheDocument();
    expect(screen.getByText('2 likes')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reply' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Back to Blog List' }));
    await expectAdminClassReturn('Blogs');
  });

  it('returns from archived assignment submissions to the Assignments tab without reply controls', async () => {
    renderRoutes();
    await openSelectedClass('Assignments');
    const archivedSection = (await screen.findByText('Archived Assignments')).parentElement.parentElement;
    fireEvent.click(within(archivedSection).getByRole('button', { name: 'View Submissions' }));

    expect(await screen.findByText('Synthetic archived submission')).toBeInTheDocument();
    expect(screen.getByText('Synthetic teacher feedback')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('Write a reply...')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reply' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back to Class' }));
    await expectAdminClassReturn('Assignments');
  });

  it('returns from Student Details to the selected class and Students tab without editable notes', async () => {
    renderRoutes();
    await openSelectedClass('Students');
    fireEvent.click(await screen.findByRole('button', { name: 'View Details' }));

    expect(await screen.findByText('Synthetic teacher note')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save Notes' })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText('Add notes about this student...')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back to Class' }));
    await expectAdminClassReturn('Students');
  });

  it('keeps post moderation available to teachers and preserves their dashboard return', async () => {
    sessionStorage.setItem('user_info', JSON.stringify({
      userId: 2,
      username: 'teacher-user',
      role: 'TEACHER',
    }));
    mocks.axios.put.mockResolvedValue({ data: { id: 7, title: 'Updated post' } });
    mocks.axios.delete.mockResolvedValue({ data: { message: 'Post deleted successfully' } });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderTeacherPost();

    expect(await screen.findByTestId('post-view-content')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Post' }));
    const editDialog = screen.getByRole('dialog', { name: 'Edit Post' });
    fireEvent.change(within(editDialog).getByLabelText('Post title'), { target: { value: 'Updated post' } });
    fireEvent.change(within(editDialog).getByLabelText('Post content'), {
      target: { value: '<p>Updated content</p>' },
    });
    fireEvent.click(within(editDialog).getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(mocks.axios.put).toHaveBeenCalledWith(
      '/classes/4/posts/7',
      expect.objectContaining({ title: 'Updated post', content: '<p>Updated content</p>' }),
    ));
    fireEvent.click(screen.getByRole('button', { name: 'Delete Post' }));
    await waitFor(() => expect(screen.getByText('Teacher dashboard')).toBeInTheDocument());
    expect(mocks.axios.delete).toHaveBeenCalledWith('/classes/4/posts/7');
    expect(JSON.parse(screen.getByTestId('location-state').textContent)).toMatchObject({
      pathname: '/teacher-dashboard',
      selectedClass: { id: selectedClass.id },
      classDetailsTab: 'Blogs',
    });
    confirm.mockRestore();
  });
});
