<?php
// Offline compatibility runner. No rfriends initializer, CLI, credentials or network.
ini_set('display_errors', '0');
ini_set('log_errors', '0');
date_default_timezone_set('Asia/Tokyo');
ob_start();
function finish_result($state, $code = null) {
    while (ob_get_level()) ob_end_clean();
    echo json_encode(['state'=>$state, 'error_code'=>$code]);
    exit;
}
set_error_handler(function() { throw new RuntimeException('php_error'); });
function import_function($source, $name) {
    $tokens = token_get_all($source); $n = count($tokens);
    for ($i=0; $i<$n; $i++) {
        if (!is_array($tokens[$i]) || $tokens[$i][0] !== T_FUNCTION) continue;
        $start = $i; $j = $i + 1;
        while (is_array($tokens[$j]) && $tokens[$j][0] === T_WHITESPACE) $j++;
        if (!is_array($tokens[$j]) || $tokens[$j][1] !== $name) continue;
        $body = ''; $depth = 0; $opened = false;
        for ($j=$start; $j<$n; $j++) {
            $t = $tokens[$j]; $body .= is_array($t) ? $t[1] : $t;
            if ($t === '{') { $depth++; $opened = true; }
            if ($t === '}' && --$depth === 0 && $opened) { eval($body); return; }
        }
    }
    throw new RuntimeException('source_missing_function');
}
try {
    if (($argv[1] ?? '') !== '--fixture') finish_result('failed', 'live_transport_not_installed');
    if (getenv('RFRIENDS_ENABLE_WRITES') === '1' || getenv('RADIOFLIX_TIMEFREE_ENABLE_WRITES') === '1') finish_result('failed', 'fixture_gate');
    $raw = stream_get_contents(STDIN, 32769);
    if (strlen($raw)>32768) throw new RuntimeException('payload_size');
    $input = json_decode($raw, true, 32, JSON_THROW_ON_ERROR);
    $job = $input['job_id']; $b = $input['broadcast'];
    if (!preg_match('/^[a-f0-9]{32}$/D', $job) || !preg_match('/^[A-Z0-9_-]{1,24}$/D', $b['station']) ||
        !preg_match('/^JP(?:[1-9]|[1-3][0-9]|4[0-7])$/D', $b['region'])) throw new RuntimeException('identity');
    $work = realpath($input['work']);
    if (!$work || !str_starts_with($work, '/tmp/') || is_link($input['work']) || $work !== $input['work']) throw new RuntimeException('path');
    if (count(scandir($work)) !== 2) throw new RuntimeException('nonempty_work');
    $scenario = $input['scenario'];
    if (!in_array($scenario, ['success','auth_failed','hls_failed','download_failed','short','publish_failed'], true)) throw new RuntimeException('scenario');
    $from = strtotime($b['starts_at']); $to = strtotime($b['ends_at']);
    $duration = $to-$from;
    if ($duration<=0 || $duration>900 || $to+120>time()) throw new RuntimeException('time');
    $radioDay = date('Y-m-d', $from-18000);
    if (time()>=strtotime($radioDay.' 05:00:00 +8 days')) finish_result('expired','expired');
    foreach (['failed_record','ts_in_ng','ts_out_ng'] as $key) if (($b['metadata'][$key] ?? null) !== '0') throw new RuntimeException('restricted');
    $manifest = json_decode(file_get_contents(__DIR__.'/source-manifest.json'),true);
    foreach ($manifest as $name=>$sha) {
        $path = $input['source_dir'].'/'.$name;
        if (is_link($path) || !hash_equals($sha,hash_file('sha256',$path))) throw new RuntimeException('source_version');
        $source = file_get_contents($path);
        foreach ($name==='rf_downloader.php' ? ['rfriends_downloader'] : ['timefree_check','calc_timefree_timeout'] as $fn) import_function($source,$fn);
    }
    require __DIR__.'/fixture-bindings.php';
    // Explicit safe globals; all file output remains inside this new empty job directory.
    $source = file_get_contents($input['source_dir'].'/rf_downloader.php');
    preg_match_all('/global \$(\w+)/', $source, $globals);
    foreach ($globals[1] as $g) if (!array_key_exists($g,$GLOBALS)) $GLOBALS[$g] = 0;
    $tmpdir=$work.'/scratch/'; mkdir($tmpdir); mkdir($work.'/output');
    $rec_extension=$dwn_extension='wav'; $ex_timefree=5; $ex_radiko=1; $ex_radiru=2; $ex_radiru_vod=9;
    $rec_normal_end=0; $rec_normal_end_plus=11; $rec_already_exist=1; $rec_not_deliver=2; $rec_abnormal_end=3;
    $tf_footer=''; $home_area_code=$area_code=$b['region']; $wget_opt_https_proxy='';
    $ffmpeg_loglevel_timefree='quiet'; $loghead_short='short-'; $loghead_bad='bad-';
    $failed_record_flag=$in_ng_flag=$out_ng_flag=0; $t_rmargin=120; $tout_rate=10; $tout_allow=60;
    $para=array_fill(0,19,';');
    $para[0]=date('YmdHis',$from); $para[1]=date('YmdHis',$to); $para[2]=$duration;
    $para[3]=$para[4]=$para[5]=0; $para[6]=$b['station']; $para[7]='radioflix-'.$job;
    $para[10]='radioflix'; $para[14]=$b['region'];
    $ret=rfriends_downloader(5,'recording',$duration,$para,0,'offline-fixture');
    if ($ret!==0 || !is_file($work.'/output/audio.wav')) finish_result('failed','downloader_failed');
    finish_result('completed');
} catch (Throwable $e) { finish_result('failed','invalid_or_failed'); }
