"""Restore an authenticated LitBlogs backup only into a fresh isolated project.

No service with public ports or SMTP access is started in the restore project.
The original database remains running throughout this rehearsal.
"""

import argparse
import json
import os
import re
import secrets
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import backup

ROLES = frozenset({'postgres', 'litblogs_runtime', 'litblogs_migrator', 'litblog_identity_owner',
                   'litblog_account_operator', 'litblog_invitation_operator', 'litblogs_backup'})


def run(command, *, data=None, timeout=180):
    return subprocess.run(command, input=data, capture_output=True, check=True, timeout=timeout,
                          env={'PATH': '/usr/bin:/bin', 'HOME': '/root', 'LANG': 'C.UTF-8',
                               'COMPOSE_PROGRESS': 'plain', 'COMPOSE_ANSI': 'never'}).stdout


def docker(*arguments, **kwargs):
    return run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', *arguments], **kwargs)


def restore_roles_sql(text):
    """The isolated Compose initializer already creates exactly these roles."""
    created = set()
    result = []
    for line in text.splitlines(keepends=True):
        match = re.fullmatch(r'CREATE ROLE ([a-z_]+);\s*', line)
        if match:
            if match[1] not in ROLES or match[1] in created:
                raise ValueError('Unexpected backup role')
            created.add(match[1])
        else:
            result.append(line)
    if created != ROLES:
        raise ValueError('Backup role set changed')
    return ''.join(result).encode()


def validate_restore_compose(config, project):
    """Reject any merge that could reuse or remove the original deployment state."""
    if not re.fullmatch(r'litblogs-cit-restore-[0-9a-f]{12}', project) or config.get('name') != project:
        raise ValueError('Invalid isolated restore project')
    expected_volumes = {'uploads', 'postgres-data', 'postgres-tls', 'postgres-ca', 'clamav-data'}
    if set(config.get('volumes', {})) != expected_volumes:
        raise ValueError('Restore volume inventory changed')
    for category in ('volumes', 'networks'):
        for key, resource in config.get(category, {}).items():
            if resource.get('external') or resource.get('name') != f'{project}_{key}':
                raise ValueError('Restore resource is not exclusive to the isolated project')
    dependencies = {'initialize': set(), 'postgres': {'initialize'}, 'migrate': {'postgres'}}
    writable = {'initialize': {'uploads', 'postgres-tls', 'postgres-ca'},
                'postgres': {'postgres-data'}, 'migrate': set()}
    for name, allowed_dependencies in dependencies.items():
        service = config['services'][name]
        if (service.get('ports') or service.get('container_name')
                or service.get('network_mode') not in (None, 'none')
                or set(service.get('depends_on', {})) != allowed_dependencies):
            raise ValueError('Restore service can reach an unapproved dependency or listener')
        for mount in service.get('volumes', []):
            if mount.get('type') == 'volume':
                if mount.get('source') not in expected_volumes:
                    raise ValueError('Restore uses an unapproved volume')
            elif not mount.get('read_only'):
                raise ValueError('Restore has a writable host mount')
            if not mount.get('read_only') and mount.get('source') not in writable[name]:
                raise ValueError('Restore writable volume does not match its service')


def rehearse(archive, *, sentinel=None):
    backup.require_host()
    project = 'litblogs-cit-restore-' + secrets.token_hex(6)
    assert re.fullmatch(r'litblogs-cit-restore-[0-9a-f]{12}', project)
    with backup.operation_lock(), backup.verified_archive(archive) as restored:
        prefix = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'compose',
                  '--project-name', project, '--project-directory', str(backup.REPO),
                  '--env-file', str(restored / 'environment'), '-f', str(backup.REPO / 'docker-compose.yml'),
                  '-f', str(backup.STATE / 'compose.yaml')]
        def compose(*args, **kwargs):
            return run([*prefix, *args], **kwargs)

        def sql(statement):
            return compose('exec', '-T', '--user', 'postgres', 'postgres', 'psql',
                           '--no-password', '-X', '-q', '-t', '-A', '--set=ON_ERROR_STOP=1',
                           '--username=postgres', '--dbname=litblogs', data=statement.encode()).decode().strip()

        # Validate the fully expanded merge before creating files, starting any
        # service, or allowing the finally block to remove project volumes.
        validate_restore_compose(json.loads(compose('config', '--format', 'json')), project)
        assert not docker('ps', '-aq', '--filter', f'label=com.docker.compose.project={project}').strip()
        assert not docker('volume', 'ls', '-q', '--filter', f'label=com.docker.compose.project={project}').strip()
        assert not docker('network', 'ls', '-q', '--filter', f'label=com.docker.compose.project={project}').strip()
        created = []
        try:
            for volume in backup.VOLUMES:
                name = f'{project}_{volume}'
                assert not docker('volume', 'ls', '-q', '--filter', f'name=^{name}$').strip()
                docker('volume', 'create', '--label', f'com.docker.compose.project={project}',
                       '--label', f'com.docker.compose.volume={volume}', name)
                created.append(name)
                record, = json.loads(docker('volume', 'inspect', name))
                destination = Path(record['Mountpoint'])
                assert record['Name'] == name and record['Driver'] == 'local' and not record.get('Options')
                assert record['Labels']['com.docker.compose.project'] == project
                assert destination.resolve() == destination and destination.name == '_data'
                assert destination.parent.name == name and not any(destination.iterdir())
                source = restored / f'{volume}.tar'
                backup.validate_volume_tar(source)
                with tarfile.open(source) as bundle:
                    # Authenticated, checksummed, explicitly validated regular files/directories only.
                    bundle.extractall(destination, filter='fully_trusted', numeric_owner=True)
            compose('up', '-d', '--no-build', '--wait', '--wait-timeout', '180', 'postgres', timeout=240)
            roles = sql("SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY rolname;")
            assert set(roles.splitlines()) == ROLES
            compose('exec', '-T', '--user', 'postgres', 'postgres', 'psql', '--no-password', '-X',
                    '--set=ON_ERROR_STOP=1', '--username=postgres', '--dbname=postgres',
                    data=restore_roles_sql((restored / 'roles.sql').read_text()), timeout=120)
            compose('exec', '-T', '--user', 'postgres', 'postgres', 'pg_restore', '--no-password',
                    '--username=postgres', '--dbname=litblogs', '--exit-on-error', '--clean', '--if-exists',
                    data=(restored / 'database.dump').read_bytes(), timeout=600)
            head_before = sql('SELECT version_num FROM alembic_version;')
            compose('run', '--rm', '--no-deps', 'migrate', timeout=1900)
            assert sql('SELECT version_num FROM alembic_version;') == head_before
            assert sql("SELECT count(*) FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='litblog_identity_owner') AND member=(SELECT oid FROM pg_roles WHERE rolname='litblogs_migrator');") == '0'
            evidence = {'restored_project': project, 'archive': str(archive), 'schema_head': head_before,
                        'authenticated_encrypted_archive': True, 'roles_and_data_restored': True,
                        'repeat_migration_preserved_schema': True, 'smtp_and_public_ingress_absent': True}
            if sentinel:
                assert re.fullmatch('[0-9a-f]{32}', sentinel)
                assert sql('SELECT value FROM litblogs_deployment_probe.persistence;') == sentinel
                sql('ALTER TABLE litblogs_deployment_probe.persistence ADD COLUMN new_column text;')
                assert sql('SELECT value FROM litblogs_deployment_probe.persistence WHERE new_column IS NULL;') == sentinel
                row, = json.loads(docker('volume', 'inspect', f'{project}_uploads'))
                upload = Path(row['Mountpoint']) / '.incoming' / f'{sentinel}.part'
                assert upload.read_text() == sentinel
                metadata = upload.stat()
                assert (metadata.st_uid, metadata.st_gid, metadata.st_mode & 0o777) == (10001, 10001, 0o600)
                evidence['database_rows_and_upload_bytes_restored'] = True
                evidence['add_column_preserved_existing_rows'] = True
            evidence['completed_at'] = datetime.now(UTC).isoformat()
            (backup.STATE / 'restore-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
            print(json.dumps(evidence, sort_keys=True))
            return evidence
        finally:
            # Only this randomly named, checked rehearsal project is eligible for cleanup.
            compose('down', '--volumes', '--timeout', '60', timeout=180)
            for name in created:
                if docker('volume', 'ls', '-q', '--filter', f'name=^{name}$').strip():
                    row, = json.loads(docker('volume', 'inspect', name))
                    assert row['Name'] == name and row['Labels']['com.docker.compose.project'] == project
                    docker('volume', 'rm', name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--sentinel')
    args = parser.parse_args()
    os.umask(0o077)
    rehearse(args.archive, sentinel=args.sentinel)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # noqa: BLE001 - suppress secret-bearing restore errors at the CLI boundary
        print('Isolated restore verification failed (' + type(error).__name__ + '); original data preserved.')
        raise SystemExit(1) from None
