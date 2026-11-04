"""Host-only runner. Docker operations are limited to one ephemeral service.

No production service restart/up/build or gate changes. Jobs only via formal admission.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import signal
import sys
import uuid
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SERVICE = 'timefree-acceptance'
OWNER = 'radioflix.acceptance.owner'
COMPOSE = ROOT / 'docker-compose.timefree-acceptance.yml'


def command(argv, *, env=None, timeout=30, check=True):
    result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise ValueError('host_command_failed')
    return result


def docker(*args, **kwargs):
    return command(['docker', *args], **kwargs)


def inspect(name):
    return json.loads(docker('inspect', name).stdout)[0]


def environment(info):
    return dict(item.split('=', 1) for item in info['Config']['Env'])


def safety():
    result = {}
    for service in ('backend', 'timefree-worker', 'rfriends-gateway', 'frontend'):
        ids = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=radioflix',
                     '--filter', 'label=com.docker.compose.service=' + service).stdout.split()
        if len(ids) != 1:
            raise ValueError('production_service_count')
        info = inspect(ids[0])
        if not info['State']['Running'] or info['RestartCount'] != 0:
            raise ValueError('production_not_stable')
        values = environment(info)
        if service != 'frontend' and values.get('RFRIENDS_ENABLE_WRITES') != '0':
            raise ValueError('native_gate_not_off')
        if service in ('backend', 'timefree-worker') and values.get('RADIOFLIX_TIMEFREE_ENABLE_WRITES') != '0':
            raise ValueError('timefree_gate_not_off')
        if service == 'timefree-worker' and (values.get('RADIOFLIX_TIMEFREE_BOOT_MODE') != 'disabled'
                or info['HostConfig']['NetworkMode'] != 'none'):
            raise ValueError('worker_not_disabled')
        mounts = {m['Destination']: m for m in info['Mounts']}
        if service == 'timefree-worker':
            for target in ('/data', '/timefree', '/recordings', '/native-reservations', '/native-timefree'):
                if target not in mounts or mounts[target]['RW']:
                    raise ValueError('worker_mount_not_readonly')
        if service == 'backend' and (mounts.get('/timefree', {}).get('RW', True) or mounts.get('/run/timefree', {}).get('RW', True)):
            raise ValueError('backend_mount_not_readonly')
        result[service] = {'id': info['Id'], 'image': info['Image'], 'started': info['State']['StartedAt']}
    native = inspect('rfriends3')
    if not native['State']['Running']:
        raise ValueError('rfriends_not_running')
    result['rfriends3'] = {'id': native['Id'], 'started': native['State']['StartedAt'],
                          'restarts': native['RestartCount']}
    # UDS, no external HTTP. Disabled factory must remain read-only and unapproved.
    probe = "import stat; from pathlib import Path; d=Path('/run/timefree'); s=d/'control.sock'; di=d.lstat(); si=s.lstat(); assert stat.S_ISDIR(di.st_mode) and (di.st_uid,di.st_gid,stat.S_IMODE(di.st_mode))==(10001,20000,0o770); assert stat.S_ISSOCK(si.st_mode) and (si.st_uid,si.st_gid,stat.S_IMODE(si.st_mode))==(10001,20000,0o660); from radioflix.timefree.transport import WorkerClient; from radioflix.timefree.control import production_worker; import os; c=WorkerClient(os.environ['RADIOFLIX_TIMEFREE_SOCKET']); h=c.request('GET','/health'); assert h['writes_enabled'] is False and h['boot_mode']=='disabled_read_only' and h['capture_ready'] is False; w=production_worker(); assert w.read_only and not w.transport.bridge_approved"
    docker('exec', result['backend']['id'], 'python', '-c', probe)
    return result


def render(image, ident, approval):
    env = {**os.environ, 'RADIOFLIX_ACCEPT_IMAGE': image, 'RADIOFLIX_ACCEPT_JOB': ident,
           'RADIOFLIX_ACCEPT_APPROVAL': str(approval)}
    base = ['compose', '-p', 'radioflix-onejob', '-f', str(COMPOSE)]
    data = json.loads(docker(*base, 'config', '--format', 'json', env=env).stdout)
    service = data['services'][SERVICE]
    if (set(data['services']) != {SERVICE} or service['image'] != image or
            service['entrypoint'] != ['python', '-m', 'radioflix.timefree.acceptance'] or
            service['command'] != ['--accept-job', ident] or service['user'] != '10001:20000' or
            service['restart'] != 'no' or not service['read_only'] or service.get('ports') or
            service.get('depends_on') or service.get('privileged') or
            service.get('network_mode') or service['cap_drop'] != ['ALL'] or
            service['security_opt'] != ['no-new-privileges:true']):
        raise ValueError('unsafe_compose')
    gates = service['environment']
    if (gates['RFRIENDS_ENABLE_WRITES'] != '0' or gates['RADIOFLIX_TIMEFREE_ENABLE_WRITES'] != '1'
            or gates['RADIOFLIX_TIMEFREE_BOOT_MODE'] != 'enabled'):
        raise ValueError('unsafe_compose_gates')
    targets = {m['target']: m for m in service['volumes']}
    if set(targets) != {'/data', '/timefree', '/recordings', '/native-reservations', '/native-timefree', '/approval.json'}:
        raise ValueError('unsafe_mounts')
    for target, mount in targets.items():
        if bool(mount.get('read_only')) != (target not in ('/data', '/timefree')):
            raise ValueError('unsafe_mount_mode')
    if set(service['networks']) != {'acceptance-egress'} or data['networks']['acceptance-egress'].get('driver') != 'bridge':
        raise ValueError('unsafe_network')
    return base, env, service, data


def probe(image, ident, service, data, *, final=False):
    args = ['run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--user', '10001:20000',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '-e', 'PYTHONDONTWRITEBYTECODE=1']
    for mount in service['volumes']:
        if mount['target'] == '/approval.json':
            continue
        source = mount['source']
        if mount['type'] == 'volume':
            source = data['volumes'][source]['name']
        args += ['--mount', f"type={mount['type']},src={source},dst={mount['target']},readonly"]
    args += ['--entrypoint', 'python', image, '-m', 'radioflix.timefree.acceptance_probe', '--job', ident]
    if final:
        args += ['--final']
    return json.loads(docker(*args).stdout)


def cleanup(directory):
    directory = Path(directory)
    record = directory / 'owner.json'
    (directory / 'admission.json').unlink(missing_ok=True)
    (directory / 'approval.json').unlink(missing_ok=True)
    if not record.exists():
        return
    owner = json.loads(record.read_text())
    name, nonce = owner['name'], owner['nonce']
    if not re.fullmatch(r'radioflix-accept-[a-f0-9]{32}', name) or not re.fullmatch(r'[a-f0-9]{32}', nonce):
        raise ValueError('cleanup_identity')
    found = docker('ps', '-aq', '--filter', 'name=^/' + name + '$').stdout.split()
    (directory / 'approval.json').unlink(missing_ok=True)
    if found:
        info = inspect(found[0])
        if info['Config']['Labels'].get(OWNER) != nonce:
            raise ValueError('cleanup_owner')
        docker('rm', '-f', name)
    if docker('ps', '-aq', '--filter', 'name=^/' + name + '$').stdout.strip():
        raise ValueError('container_remaining')
    networks = docker('network', 'ls', '-q', '--filter',
                      'label=com.docker.compose.project=radioflix-onejob').stdout.split()
    for network_id in networks:
        network = json.loads(docker('network', 'inspect', network_id).stdout)[0]
        labels = network.get('Labels') or {}
        if (labels.get('com.docker.compose.project') != 'radioflix-onejob'
                or labels.get('com.docker.compose.network') != 'acceptance-egress'):
            raise ValueError('network_owner')
        if network.get('Containers'):
            raise ValueError('network_in_use')
        docker('network', 'rm', network_id)
    (directory / 'approval.json').unlink(missing_ok=True)


def smoke():
    def get(url, headers=None):
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as r:
            return r.status, r.read(2 * 1024 * 1024)
    for url in ('http://127.0.0.1:3001/', 'http://127.0.0.1:8001/', 'http://127.0.0.1:8001/openapi.json'):
        if get(url)[0] != 200:
            raise ValueError('smoke_status')
    status, body = get('http://127.0.0.1:8001/api/programs')
    if status != 200:
        raise ValueError('smoke_programs')
    # Bounded inventory traversal: no media body except a 1024-byte Range.
    from urllib.parse import quote
    for program in json.loads(body)[:20]:
        _, episodes = get('http://127.0.0.1:8001/api/programs/' + quote(program['id'], safe='') + '/episodes')
        for episode in json.loads(episodes):
            if episode.get('source', 'normal') == 'normal':
                path = episode['audio_url']
                if not path.startswith('/audio/') or '..' in path or '\\' in path:
                    raise ValueError('smoke_audio_path')
                status, body = get('http://127.0.0.1:8001' + path, {'Range': 'bytes=0-1023'})
                if status != 206 or len(body) != 1024:
                    raise ValueError('smoke_range')
                return
    raise ValueError('smoke_normal_asset_missing')


def execution_context(ident, directory):
    if not re.fullmatch('[a-f0-9]{32}', ident):
        raise ValueError('invalid_job_id')
    head = command(['git', 'rev-parse', 'HEAD']).stdout.strip()
    if head != command(['git', 'rev-parse', 'origin/main']).stdout.strip():
        raise ValueError('revision_not_synced')
    if command(['git', 'status', '--porcelain', '--', 'backend/radioflix', 'backend/tests', 'backend/Dockerfile.timefree-acceptance', 'scripts', COMPOSE.name]).stdout:
        raise ValueError('uncommitted_execution_code')
    if docker('ps', '-aq', '--filter', 'label=com.docker.compose.service=timefree-acceptance').stdout.strip():
        raise ValueError('acceptance_container_exists')
    existing_networks = docker('network', 'ls', '-q', '--filter',
                               'label=com.docker.compose.project=radioflix-onejob').stdout.strip()
    if existing_networks:
        raise ValueError('acceptance_network_exists')
    before = safety()
    image = 'radioflix-timefree-acceptance:' + head
    acceptance_image = json.loads(docker('image', 'inspect', image).stdout)[0]
    if acceptance_image['Config']['Labels'].get('org.opencontainers.image.revision') != head:
        raise ValueError('acceptance_image_revision_mismatch')
    for role in ('backend', 'timefree-worker'):
        info = json.loads(docker('image', 'inspect', before[role]['image']).stdout)[0]
        if info['Config']['Labels'].get('org.opencontainers.image.revision') != head:
            raise ValueError('image_revision_mismatch')
    approval = Path(directory) / 'approval.json'
    base, env, service, data = render(image, ident, approval)
    return image, base, env, service, data, before


def run(ident, directory, *, execute=False):
    image, base, env, service, data, before = execution_context(ident, directory)
    head = image.rsplit(':', 1)[1]
    approval = Path(directory) / 'approval.json'
    state = probe(image, ident, service, data)
    print(json.dumps({'dry_run': not execute, 'job': state, 'revision': head, 'image': image,
        'approval': str(approval), 'command': service['entrypoint'] + service['command'],
        'user': service['user'], 'mounts': service['volumes'], 'gates': service['environment']}, sort_keys=True), flush=True)
    if not execute:
        return 0
    nonce = uuid.uuid4().hex
    name = 'radioflix-accept-' + ident
    record = Path(directory) / 'owner.json'
    with record.open('x') as stream:
        json.dump({'name': name, 'nonce': nonce}, stream)
    result = None
    try:
        # Root helper can only write this new private temp dir. No production mounts/network.
        script = "import os,json; from datetime import datetime,timezone,timedelta; p='/out/approval.json'; f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); os.fchown(f,10001,20000); s=os.fdopen(f,'w'); json.dump({'job_id':'" + ident + "','approved':True,'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()},s); s.close()"
        docker('run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--user', '0:0',
               '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--security-opt', 'no-new-privileges:true',
               '--mount', f'type=bind,src={directory},dst=/out', '--entrypoint', 'python', image, '-c', script)
        if safety() != before:
            raise ValueError('production_changed_before_capture')
        probe(image, ident, service, data)  # exact queued job / conflicts immediately before start
        result = docker(*base, 'run', '--rm', '--no-deps', '--pull', 'never', '--name', name,
                        '--label', OWNER + '=' + nonce, SERVICE, env=env, timeout=600, check=False)
    finally:
        cleanup(directory)
        if safety() != before:
            raise ValueError('production_changed')
        smoke()
    final = probe(image, ident, service, data, final=True)
    print(json.dumps({'final': final, 'process_remaining': 0, 'approval_deleted': not approval.exists(),
                      'normal_smoke': 'PASS', 'production_gates': 0}, sort_keys=True))
    if result is None or result.returncode or final['state'] != 'completed':
        return 1
    return 0


def target_arguments(target):
    from datetime import date
    if set(target) != {'broadcast_episode_id', 'schedule_revision', 'date'}:
        raise ValueError('invalid_target')
    if any(not re.fullmatch('[a-f0-9]{64}', target[k]) for k in ('broadcast_episode_id', 'schedule_revision')):
        raise ValueError('invalid_target')
    date.fromisoformat(target['date'])
    return ['--episode-id', target['broadcast_episode_id'], '--schedule-revision',
            target['schedule_revision'], '--date', target['date']]


def owner_record(directory):
    record = {'name': 'radioflix-accept-' + uuid.uuid4().hex, 'nonce': uuid.uuid4().hex}
    with (Path(directory) / 'owner.json').open('x') as stream:
        json.dump(record, stream)
    return record


def owned_args(directory):
    record = json.loads((Path(directory) / 'owner.json').read_text())
    return ['--name', record['name'], '--label', OWNER + '=' + record['nonce']]


def write_authorization(image, directory, filename, payload):
    # Separate purposes, neither authorization can be interpreted as the other.
    if filename not in ('admission.json', 'approval.json'):
        raise ValueError('invalid_approval_name')
    script = ("import os,json,sys; from datetime import datetime,timezone,timedelta; "
              "data=json.loads(sys.argv[2]); data.update(approved=True,expires_at="
              "(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()); "
              "f=os.open('/out/'+sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); "
              "os.fchown(f,10001,20000); s=os.fdopen(f,'w'); json.dump(data,s); s.close()")
    docker('run', '--rm', '--pull', 'never', *owned_args(directory), '--network', 'none',
           '--read-only', '--user', '0:0', '--cap-drop', 'ALL', '--cap-add', 'CHOWN',
           '--security-opt', 'no-new-privileges:true', '--mount', f'type=bind,src={directory},dst=/out',
           '--entrypoint', 'python', image, '-c', script, filename, json.dumps(payload))


def admission_call(image, target, service, data, directory, *, execute=False):
    # Official schedule metadata uses HTTPS in future production. This function
    # is replaced at the Docker boundary in offline fixtures, never env-selected.
    args = ['run', '--rm', '--pull', 'never', '--network', 'bridge', '--read-only',
            '--user', '10001:20000', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'RFRIENDS_ENABLE_WRITES=0',
            '-e', 'RADIOFLIX_TIMEFREE_ENABLE_WRITES=0', '-e', 'RADIOFLIX_TIMEFREE_BOOT_MODE=disabled',
            '-e', 'RADIOFLIX_DB_PATH=/data/radioflix.sqlite3',
            '-e', 'RADIOFLIX_NATIVE_RESERVATIONS_DIR=/native-reservations']
    args += owned_args(directory)
    for mount in service['volumes']:
        if mount['target'] == '/approval.json':
            continue
        source = data['volumes'][mount['source']]['name'] if mount['type'] == 'volume' else mount['source']
        mode = '' if execute and mount['target'] == '/data' else ',readonly'
        args += ['--mount', f"type={mount['type']},src={source},dst={mount['target']}{mode}"]
    if execute:
        args += ['--mount', f'type=bind,src={directory}/admission.json,dst=/admission.json,readonly',
                 '-e', 'RADIOFLIX_TIMEFREE_ADMISSION_APPROVAL_FILE=/admission.json']
    args += ['--entrypoint', 'python', image, '-m', 'radioflix.timefree.admission',
             *target_arguments(target), '--execute' if execute else '--dry-run']
    return json.loads(docker(*args, timeout=180).stdout)


def check_handoff(result, target, expected_count):
    if (not re.fullmatch('[a-f0-9]{32}', result.get('job_id', '')) or result.get('state') != 'queued'
            or result.get('job_count') != expected_count
            or any(result.get('target', {}).get(k) != v for k, v in target.items())):
        raise ValueError('admission_handoff_invalid')
    return result['job_id']


def check_target_probe(state, ident, target, count):
    if (state.get('job_id') != ident or state.get('state') != 'queued' or state.get('job_count') != count
            or any(state.get(k) != target[k] for k in ('broadcast_episode_id', 'schedule_revision'))):
        raise ValueError('exact_target_required')


def run_target(target, directory, *, execute=False):
    target_arguments(target)
    directory = Path(directory)
    owner_record(directory)  # metadata only, never an authorization
    try:
        return _run_target(target, directory, execute=execute)
    finally:
        if (directory / 'owner.json').exists():
            cleanup(directory)
            (directory / 'owner.json').unlink()


def _run_target(target, directory, *, execute=False):
    target_arguments(target)
    directory = Path(directory)
    image, base, env, service, data, before = execution_context('0'*32, directory)
    preview = admission_call(image, target, service, data, directory)
    candidate = preview.get('target', {})
    if preview.get('state') != 'eligible' or any(candidate.get(k) != v for k, v in target.items()):
        raise ValueError('candidate_invalid')
    summary = {**candidate, 'dry_run': not execute, 'job_id': None, 'final_state': 'eligible',
               'output_count': 0, 'published_count': 0, 'approval_cleanup': True,
               'process_remaining': 0, 'range_check': 'NOT RUN', 'final_gates': 'NOT CHECKED',
               'limits': {'program': 300, 'audio': 302, 'segments': 62, 'wire': 73},
               'topology': {'user': service['user'], 'mounts': service['volumes'],
                            'networks': service['networks'], 'image': image}}
    if not execute:
        if safety() != before:
            raise ValueError('production_changed')
        cleanup(directory)
        (directory / 'owner.json').unlink()
        summary['final_gates'] = 'OFF'
        print(json.dumps(summary, sort_keys=True), flush=True)
        return 0
    result = None
    code = 2
    try:
        # Repeat read-only checks immediately before admission, with no mutation.
        if safety() != before or admission_call(image, target, service, data, directory) != preview:
            raise ValueError('preflight_changed')
        write_authorization(image, directory, 'admission.json', target)
        summary['final_state'] = 'admission_unknown'
        result = admission_call(image, target, service, data, directory, execute=True)
        ident = check_handoff(result, target, candidate['existing_job_count'] + 1)
        summary['job_id'] = ident
        summary['final_state'] = 'queued'
        (directory / 'admission.json').unlink(missing_ok=True)
        base, env, service, data = render(image, ident, directory / 'approval.json')
        check_target_probe(probe(image, ident, service, data), ident, target, result['job_count'])
        if safety() != before:
            raise ValueError('production_changed')
        write_authorization(image, directory, 'approval.json', {'job_id': ident})
        # Bind the job-only capture authorization to the already-validated target.
        check_target_probe(probe(image, ident, service, data), ident, target, result['job_count'])
        summary['final_state'] = 'unknown'
        process = docker(*base, 'run', '--rm', '--no-deps', '--pull', 'never',
                         *owned_args(directory), SERVICE, env=env, timeout=600, check=False)
        final = probe(image, ident, service, data, final=True)
        if (final.get('job_id') != ident or final.get('job_count') != result['job_count']
                or any(final.get(k) != target[k] for k in ('broadcast_episode_id', 'schedule_revision'))):
            raise ValueError('final_identity_changed')
        summary.update(final_state=final['state'], output_count=final['output_count'],
                       published_count=final['published_count'])
        code = 0 if (process.returncode == 0 and final['state'] == 'completed'
                     and final['output_count'] == final['published_count'] == 1) else 1
    except Exception:
        # Never infer completion or retry after an uncertain admission/launch response.
        summary['error'] = 'acceptance_stopped_inspect_read_only'
    finally:
        try:
            cleanup(directory)
            summary['approval_cleanup'] = not any((directory / n).exists() for n in ('admission.json', 'approval.json'))
            (directory / 'owner.json').unlink()
        except Exception:
            summary['approval_cleanup'] = False
            summary['process_remaining'] = 'UNKNOWN'
            code = 2
        try:
            smoke()
            summary['range_check'] = 'PASS'
        except Exception:
            summary['range_check'] = 'FAIL'
            code = 2
        try:
            if safety() != before:
                raise ValueError('production_changed')
            summary['final_gates'] = 'OFF'
        except Exception:
            summary['final_gates'] = 'UNVERIFIED'
            code = 2
        print(json.dumps(summary, sort_keys=True), flush=True)
    return code


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir')
    parser.add_argument('--cleanup')
    parser.add_argument('--job', help='legacy exact-job path; never admits')
    parser.add_argument('--episode-id')
    parser.add_argument('--schedule-revision')
    parser.add_argument('--date')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        if args.cleanup:
            cleanup(args.cleanup)
            return 0
        if not args.run_dir:
            parser.error('shell runner required')
        if args.job:
            if args.episode_id or args.schedule_revision or args.date:
                parser.error('choose job or explicit target')
            return run(args.job, args.run_dir, execute=args.execute)
        if not all((args.episode_id, args.schedule_revision, args.date)):
            parser.error('--episode-id, --schedule-revision and --date required')
        return run_target({'broadcast_episode_id': args.episode_id,
                           'schedule_revision': args.schedule_revision, 'date': args.date},
                          args.run_dir, execute=args.execute)
    except Exception:
        print('onejob runner stopped; inspect job read-only; do not retry', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
