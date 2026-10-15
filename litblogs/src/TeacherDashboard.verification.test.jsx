import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import TeacherDashboard from './TeacherDashboard';

const doubles = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('axios', () => ({ default: { get: doubles.get, post: doubles.post } }));
vi.mock('./components/Navbar', () => ({ default: () => <nav>Teacher navigation</nav> }));
vi.mock('./components/Footer', () => ({ default: () => <footer>Teacher footer</footer> }));
vi.mock('./components/ClassDetails', () => ({ default: () => <div>Class details</div> }));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  doubles.get.mockImplementation(async (path) => {
    if (path === '/teacher/dashboard') return { data: { name: 'Example Teacher' } };
    if (path === '/teacher/analytics') return { data: {} };
    if (path.startsWith('/classes')) return { data: [] };
    throw new Error('Unexpected endpoint');
  });
});

it('lets teachers help unverified students before anyone has enrolled in a class', async () => {
  render(<MemoryRouter><TeacherDashboard /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Students' }));
  expect(screen.getByText('Create classes to enroll students')).toBeInTheDocument();
  const verify = screen.getByRole('button', { name: 'Verify students' });
  verify.focus();
  fireEvent.click(verify);
  expect(screen.getByRole('dialog', { name: 'Verify students' })).toBeInTheDocument();
  expect(screen.getByLabelText('Student school email addresses')).toHaveFocus();
  expect(doubles.post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(verify).toHaveFocus();
});
