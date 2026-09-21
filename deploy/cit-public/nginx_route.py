"""Stage and atomically replace only the existing CIT LitBlogs Nginx location."""
import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

STATE = Path('/home/litblogs/.local/state/cit-deploy/public-route')
SITE = Path('/etc/nginx/sites-available/default')
LINK = Path('/etc/nginx/sites-enabled/default')
MAIN = Path('/etc/nginx/nginx.conf')
STAGED_FILES = frozenset({'default.before', 'default.candidate', 'nginx-test.conf', 'nginx-rollback-test.conf'})


def replace_location(original, replacement):
    matches = list(re.finditer(r'(?m)^[ \t]*location[ \t]+/dren[ \t]*\{', original))
    if len(matches) != 1:
        raise ValueError('Expected exactly one original lowercase LitBlogs location')
    match = matches[0]
    start = match.start()
    previous_start = original.rfind('\n', 0, max(0, start - 1)) + 1
    if original[previous_start:start].strip().startswith('# /dren ->'):
        start = previous_start
    depth, quote, escaped, comment = 1, None, False, False
    for position in range(match.end(), len(original)):
        character = original[position]
        if comment:
            if character == '\n':
                comment = False
            continue
        if escaped:
            escaped = False
            continue
        if character == '\\':
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == '#':
            comment = True
        elif character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
            if depth == 0:
                end = position + 1
                if original[end:end + 2] == '\r\n':
                    end += 2
                elif original[end:end + 1] == '\n':
                    end += 1
                return original[:start] + replacement + original[end:]
    raise ValueError('Original LitBlogs location is unterminated')


def command(arguments):
    subprocess.run(arguments, check=True, timeout=45, capture_output=True,
                   env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def configuration_snapshot():
    """Hash the installed config tree, including file-symlink targets, privately."""
    if SITE.resolve() != SITE or LINK.resolve() != SITE:
        raise ValueError('The shared Nginx target changed')
    root = MAIN.parent
    records = {}
    for path in sorted(root.rglob('*')):
        if len(records) >= 4096:
            raise ValueError('Shared configuration inventory exceeds its bound')
        information = path.lstat()
        entry = {'mode': stat.S_IMODE(information.st_mode),
                 'uid': information.st_uid, 'gid': information.st_gid}
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_file():
                raise ValueError('Shared configuration has an unsupported symbolic link')
            entry.update(kind='symlink', link=os.readlink(path), target=str(target))
        elif stat.S_ISDIR(information.st_mode):
            entry['kind'] = 'directory'
            records[str(path.relative_to(root))] = entry
            continue
        elif stat.S_ISREG(information.st_mode):
            target = path
            entry['kind'] = 'file'
        else:
            raise ValueError('Shared configuration contains a special file')
        target_information = target.stat()
        if target_information.st_size > 4 * 1024 * 1024:
            raise ValueError('Shared configuration file exceeds its bound')
        entry['target_mode'] = stat.S_IMODE(target_information.st_mode)
        entry['target_uid'] = target_information.st_uid
        entry['target_gid'] = target_information.st_gid
        # The site's contents are checked separately at every transition; retain
        # its metadata and symlink identities while permitting our own replacement.
        entry['sha256'] = 'litblogs-site' if target == SITE else digest(target.read_bytes())
        records[str(path.relative_to(root))] = entry
    return records


def assert_current(metadata, expected):
    if SITE.read_bytes() != expected or configuration_snapshot() != metadata['configuration']:
        raise ValueError('Shared configuration changed; refusing activation or reload')
    if 'relative_includes' in metadata:
        check_relative_includes(metadata)


def create_relative_includes():
    """Preserve Nginx's -c-directory prefix without editing shared include files."""
    targets = {path.name: str(path) for path in sorted(MAIN.parent.iterdir())}
    reserved = STAGED_FILES | {'metadata.json', 'nginx-dren.conf', 'nginx_route.py'}
    if set(targets) & reserved or any(
        (STATE / name).exists() or (STATE / name).is_symlink() for name in targets
    ):
        raise ValueError('Relative include mirror collides with existing staging files')
    for name, target in targets.items():
        (STATE / name).symlink_to(target, target_is_directory=Path(target).is_dir())
    return targets


def check_relative_includes(metadata):
    expected = {path.name: str(path) for path in sorted(MAIN.parent.iterdir())}
    if metadata.get('relative_includes') != expected:
        raise ValueError('Staged relative include inventory changed')
    if {path.name for path in STATE.iterdir() if path.is_symlink()} != set(expected):
        raise ValueError('Staged relative include links changed')
    owner = STATE.stat().st_uid
    for name, target in expected.items():
        mirror = STATE / name
        information = mirror.lstat()
        if not stat.S_ISLNK(information.st_mode) or information.st_uid != owner or os.readlink(mirror) != target:
            raise ValueError('Staged relative include custody changed')
        if mirror.resolve(strict=True) != Path(target).resolve(strict=True):
            raise ValueError('Staged relative include target changed')


def read_stage_file(name):
    path = STATE / name
    information = path.lstat()
    if (not stat.S_ISREG(information.st_mode) or information.st_nlink != 1
            or information.st_uid != STATE.stat().st_uid
            or (os.name == 'posix' and stat.S_IMODE(information.st_mode) != 0o600)):
        raise ValueError('Private staging file custody changed')
    return path.read_bytes()


def write_stage_file(name, content):
    descriptor = os.open(STATE / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_site(data, metadata):
    descriptor, temporary = tempfile.mkstemp(prefix='.litblogs-dren-', dir=SITE.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), metadata['mode'])
            os.fchown(handle.fileno(), metadata['uid'], metadata['gid'])
            os.fsync(handle.fileno())
        os.replace(temporary, SITE)
        fsync_directory(SITE.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def require_host():
    if os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('This installation operation requires the CIT root shell')
    if SITE.resolve() != SITE or LINK.resolve() != SITE:
        raise ValueError('The shared Nginx target changed')
    metadata = STATE.lstat()
    if STATE.resolve() != STATE or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError('The private staging directory has unexpected custody')


def stage():
    configuration = configuration_snapshot()
    original, main = SITE.read_bytes(), MAIN.read_bytes()
    candidate = replace_location(original.decode(), (STATE / 'nginx-dren.conf').read_text()).encode()
    if candidate == original:
        raise ValueError('No new LitBlogs route was prepared')
    includes = 'include /etc/nginx/sites-enabled/*;'
    if main.decode().count(includes) != 1:
        raise ValueError('Expected one enabled-sites include in the main configuration')
    paths = []
    for path in sorted(LINK.parent.iterdir()):
        if not path.is_file() or any(value in str(path) for value in ('"', '\n', '\r')):
            raise ValueError('Unexpected enabled-site entry')
        paths.append(STATE / 'default.candidate' if path == LINK else path)
    test_main = main.decode().replace(includes, '\n'.join(f'include "{path}";' for path in paths))
    rollback_main = main.decode().replace(includes, '\n'.join(
        f'include "{STATE / "default.before" if path == STATE / "default.candidate" else path}";'
        for path in paths))
    metadata = SITE.stat()
    files = [('default.before', original), ('default.candidate', candidate),
             ('nginx-test.conf', test_main.encode()), ('nginx-rollback-test.conf', rollback_main.encode())]
    record = {'original_sha256': digest(original), 'candidate_sha256': digest(candidate),
              'main_sha256': digest(main), 'uid': metadata.st_uid, 'gid': metadata.st_gid,
              'mode': stat.S_IMODE(metadata.st_mode), 'configuration': configuration,
              'staged_sha256': {name: digest(content) for name, content in files}}
    assert_current(record, original)
    record['relative_includes'] = create_relative_includes()
    check_relative_includes(record)
    # Exclusive files ensure a repeated invocation never overwrites the rollback copy.
    for name, content in [*files, ('metadata.json', json.dumps(record).encode())]:
        write_stage_file(name, content)
    fsync_directory(STATE)
    command(['/usr/sbin/nginx', '-t', '-p', '/etc/nginx/', '-c', str(STATE / 'nginx-test.conf')])
    assert_current(record, original)
    print('Complete candidate Nginx configuration passed syntax validation; live file unchanged.')


def load_stage():
    metadata = json.loads(read_stage_file('metadata.json'))
    check_relative_includes(metadata)
    if set(metadata['staged_sha256']) != STAGED_FILES:
        raise ValueError('Staged configuration inventory changed')
    for name in STAGED_FILES:
        if digest(read_stage_file(name)) != metadata['staged_sha256'][name]:
            raise ValueError('Staged configuration bytes changed')
    original, candidate = read_stage_file('default.before'), read_stage_file('default.candidate')
    if digest(original) != metadata['original_sha256'] or digest(candidate) != metadata['candidate_sha256']:
        raise ValueError('Staged configuration bytes changed')
    return metadata, original, candidate


def recover(previous, attempted, metadata, *, reload_attempted):
    current = SITE.read_bytes()
    if current == previous and not reload_attempted:
        return  # The atomic write failed before replacing the file.
    if current != attempted:
        raise ValueError('Concurrent shared-site edit prevents automatic recovery')
    atomic_site(previous, metadata)
    # Restore only our bytes, then refuse a reload if another project changed.
    assert_current(metadata, previous)
    command(['/usr/sbin/nginx', '-t'])
    assert_current(metadata, previous)
    if reload_attempted:
        command(['/usr/bin/systemctl', 'reload', 'nginx'])
        assert_current(metadata, previous)


def activate(previous, candidate, metadata, validation_name):
    assert_current(metadata, previous)
    command(['/usr/sbin/nginx', '-t', '-p', '/etc/nginx/', '-c', str(STATE / validation_name)])
    assert_current(metadata, previous)
    reload_attempted = False
    try:
        atomic_site(candidate, metadata)
        assert_current(metadata, candidate)
        command(['/usr/sbin/nginx', '-t'])
        assert_current(metadata, candidate)
        reload_attempted = True
        command(['/usr/bin/systemctl', 'reload', 'nginx'])
        assert_current(metadata, candidate)
    except Exception:  # noqa: BLE001 - recover after any ambiguous write or reload failure
        recover(previous, candidate, metadata, reload_attempted=reload_attempted)
        raise


def commit():
    metadata, original, candidate = load_stage()
    activate(original, candidate, metadata, 'nginx-test.conf')
    print('Only the staged LitBlogs location was replaced; nginx -t passed before reload.')


def rollback():
    metadata, original, candidate = load_stage()
    activate(candidate, original, metadata, 'nginx-rollback-test.conf')
    print('Original LitBlogs route restored and Nginx reloaded after syntax validation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'commit', 'rollback'))
    args = parser.parse_args()
    os.umask(0o077)
    require_host()
    {'stage': stage, 'commit': commit, 'rollback': rollback}[args.action]()


if __name__ == '__main__':
    main()
