<?php
// RadioFlix standalone driver. No require/include, no rfriends initialization.
// Only files with a matching immutable ownership journal may be changed.
date_default_timezone_set('Asia/Tokyo');
putenv('TZ=Asia/Tokyo');
function fail_driver($code) { echo json_encode(['error' => $code]); exit(0); }
function run_command($command, $input = '') {
    $proc = proc_open($command, [0 => ['pipe','r'], 1 => ['pipe','w'], 2 => ['pipe','w']], $pipes);
    if (!is_resource($proc)) fail_driver('unknown');
    fwrite($pipes[0], $input); fclose($pipes[0]);
    $out = stream_get_contents($pipes[1]); fclose($pipes[1]);
    $err = stream_get_contents($pipes[2]); fclose($pipes[2]);
    return [proc_close($proc), $out, $err];
}
function jobs_for($command) {
    [$code, $out] = run_command(['atq']);
    if ($code !== 0) fail_driver('unknown');
    $jobs = [];
    foreach (explode("\n", trim($out)) as $line) {
        if (!preg_match('/^(\d+)\s/', $line, $match)) continue;
        [$status, $body] = run_command(['at', '-c', $match[1]]);
        if ($status !== 0) fail_driver('unknown');
        if (in_array($command, explode("\n", $body), true)) $jobs[] = $match[1];
    }
    return $jobs;
}
function write_new_or_same($path, $content) {
    if (is_link($path)) fail_driver('ownership');
    if (file_exists($path)) {
        if (file_get_contents($path) !== $content) fail_driver('ownership');
        return;
    }
    $file = @fopen($path, 'x');
    if ($file === false) fail_driver('unknown');
    $ok = fwrite($file, $content) === strlen($content);
    fflush($file); fclose($file);
    if (!$ok) fail_driver('unknown');
}
try {
    $request = json_decode(base64_decode($argv[1], true), true, 32, JSON_THROW_ON_ERROR);
    $job = $request['job']; $config = $request['config']; $operation = $request['operation'];
    if (!in_array($operation, ['inspect','create','cancel'], true)) fail_driver('incompatible');
    $id = $job['id']; $station = $job['station']; $region = $job['region'];
    if (!preg_match('/^[a-f0-9]{32}$/D', $id) || !preg_match('/^[A-Z0-9_-]{1,24}$/D', $station)) fail_driver('incompatible');
    if (!preg_match('/^JP(?:[1-9]|[1-3][0-9]|4[0-7])$/D', $region)) fail_driver('incompatible');
    $base = rtrim($config['base'], '/'); $tmp = rtrim($config['tmp'], '/'); $queue = $config['queue'];
    if (!preg_match('/^[a-z]$/D', $queue) || !is_dir($base.'/rsv') || !is_dir($tmp) ||
        !is_file($base.'/script/rfriends_rec.php') || !is_file($base.'/script/rfriends_rec_fin.php')) fail_driver('incompatible');
    $start = strtotime($job['starts_at']); $end = strtotime($job['ends_at']);
    if ($start === false || $end === false || $end <= $start || $end - $start > 86400) fail_driver('incompatible');
    $name = date('Ymd_His', $start).'_'.date('His', $end).'_'.$station.'_radioflix_'.$id;
    $dir = $base.'/rsv'; $path = $dir.'/'.$name;
    $journalDir = $dir.'/.radioflix'; $journal = $journalDir.'/'.$id.'.json';
    $command = 'sh '.escapeshellarg($path.'.sh').' # radioflix:'.$id;
    $title = preg_replace('/\s+/u', '-', trim($job['title']));
    if (!$title || strlen($title) > 1500 || strpos($title, "\0") !== false) fail_driver('incompatible');
    $data = implode(' ', [date('YmdHis', $start), date('YmdHis', $end), sprintf('%05d', $end-$start),
                         '0', '0', '0', $station, $title, ';', ';', 'radioflix-'.$id,
                         ';', ';', ';', $region, ';', ';', ';', ';'])."\n";
    $argument = escapeshellarg('0,1,1,'.$name);
    $script = "#!/bin/sh\n".
        'printf started > '.escapeshellarg($journal.'.started')." || exit 1\n".
        'cd '.escapeshellarg($base.'/script')." || exit 1\n".
        'php '.escapeshellarg($base.'/script/rfriends_rec.php').' '.$argument." < /dev/null > /dev/null 2>&1\n".
        'php '.escapeshellarg($base.'/script/rfriends_rec_fin.php').' '.$argument." > /dev/null 2>&1\n".
        'printf finished > '.escapeshellarg($journal.'.finished')."\n";
    $identity = hash('sha256', $data.$script);
    $initialJournal = json_encode(['identity'=>$identity, 'name'=>$name]);
    if (is_link($journalDir) || is_link($journal)) fail_driver('ownership');
    if (!is_dir($journalDir)) {
        if ($operation === 'inspect' || $operation === 'cancel') {
            if (count(jobs_for($command)) || file_exists($path.'.dat') || file_exists($path.'.sh')) fail_driver('ownership');
            echo json_encode(['state'=>'absent']); exit(0);
        }
        if (!mkdir($journalDir, 0700) && !is_dir($journalDir)) fail_driver('unknown');
    }
    $lock = fopen($journalDir.'/lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX)) fail_driver('unknown');
    $owned = null;
    if (file_exists($journal)) {
        $owned = json_decode(file_get_contents($journal), true, 32, JSON_THROW_ON_ERROR);
        if (($owned['identity'] ?? '') !== $identity || ($owned['name'] ?? '') !== $name) fail_driver('ownership');
    }
    $jobs = jobs_for($command);
    if (count($jobs) > 1 || (count($jobs) && !$owned)) fail_driver('ownership');
    if (!$owned && (file_exists($path.'.dat') || file_exists($path.'.sh'))) fail_driver('ownership');
    $now = time();
    $state = count($jobs) ? 'scheduled' : 'absent';
    if (count($jobs)) {
        foreach (['.dat'=>$data, '.sh'=>$script] as $ext=>$expected) {
            if (is_link($path.$ext) || !is_file($path.$ext) || file_get_contents($path.$ext) !== $expected) fail_driver('ownership');
        }
        // Recover a response lost between at registration and journal completion.
        write_new_or_same($journal.'.submitted', 'submitted');
    }
    if ($owned && file_exists($journal.'.cancelled')) {
        if (count($jobs)) fail_driver('ownership');
        $state = 'cancelled';
    } elseif ($owned && !count($jobs)) {
        if (file_exists($journal.'.finished') && $now >= $end) $state = 'elapsed';
        elseif (file_exists($journal.'.started')) $state = 'running';
        // A missing at job alone is NOT evidence that it ran or finished.
        elseif (file_exists($journal.'.submitted') && $now >= intdiv($start-120,60)*60) fail_driver('unknown');
    }
    if ($operation === 'inspect') {
        echo json_encode(['state'=>$state, 'name'=>$name, 'job_id'=>$jobs[0] ?? null]); exit(0);
    }
    if ($operation === 'cancel') {
        if ($state === 'running' || (count($jobs) && $now >= intdiv($start-120,60)*60)) fail_driver('too_late');
        if (!$owned) { echo json_encode(['state'=>'absent']); exit(0); }
        if ($state === 'elapsed' || $state === 'cancelled') { echo json_encode(['state'=>$state]); exit(0); }
        // Validate BOTH files before removing any job or file.
        foreach (['.dat'=>$data, '.sh'=>$script] as $ext=>$expected) {
            if (is_link($path.$ext) || (file_exists($path.$ext) && file_get_contents($path.$ext) !== $expected)) fail_driver('ownership');
        }
        foreach ($jobs as $number) {
            [$status] = run_command(['atrm', $number]);
            if ($status !== 0) fail_driver('unknown');
        }
        if (count(jobs_for($command))) fail_driver('unknown');
        foreach (['.dat','.sh'] as $ext) {
            if (file_exists($path.$ext) && !unlink($path.$ext)) fail_driver('unknown');
        }
        write_new_or_same($journal.'.cancelled', 'cancelled');
        echo json_encode(['state'=>'cancelled', 'name'=>$name]); exit(0);
    }
    if ($state === 'scheduled') {
        // Response may have been lost; return the existing owned job, never replace it.
        write_new_or_same($path.'.dat', $data); write_new_or_same($path.'.sh', $script);
        write_new_or_same($journal.'.submitted', 'submitted');
        echo json_encode(['state'=>'scheduled','name'=>$name,'job_id'=>$jobs[0]]); exit(0);
    }
    if ($state !== 'absent' || $start <= $now + 180) fail_driver('too_late');
    // Existing native reservations are strictly read-only. Refuse overlapping slots.
    foreach (glob($dir.'/*.dat') as $existing) {
        if ($existing === $path.'.dat' && $owned) continue;
        $parts = explode(' ', trim(file_get_contents($existing)));
        if (count($parts) < 7 || $parts[6] !== $station) continue;
        $from = strtotime($parts[0]); $to = strtotime($parts[1]);
        if ($from === false || $to === false) fail_driver('conflict');
        if ($from < $end && $to > $start) fail_driver('conflict');
    }
    if (!$owned) write_new_or_same($journal, $initialJournal);
    write_new_or_same($path.'.dat', $data); write_new_or_same($path.'.sh', $script);
    [$status] = run_command(['at','-q',$queue,'-t',date('YmdHi', $start-120)], $command."\n");
    if ($status !== 0) fail_driver('unknown');
    $jobs = jobs_for($command);
    if (count($jobs) !== 1) fail_driver('unknown');
    write_new_or_same($journal.'.submitted', 'submitted');
    echo json_encode(['state'=>'scheduled','name'=>$name,'job_id'=>$jobs[0]]);
} catch (Throwable $error) {
    // Do not leak exception text or rfriends settings into responses/logs.
    fail_driver('unknown');
}
