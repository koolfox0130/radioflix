<?php
// Deliberately no exec/system/network bindings. Used only by --fixture runner.
function echo_prn(...$args) {}
function start_prn(...$args) {}
function time_prn(...$args) {}
function stat_prn(...$args) {}
function rf_title_disp(...$args) {}
function rf_error_log(...$args) {}
function rf_error_log_ffmpeg(...$args) {}
function rf_error_message(...$args) {}
function rf_rate_disp(...$args) {}
function disp_mediainfo(...$args) {}
function clear_log_hour(...$args) { return true; }
function get_recdir(...$args) { return $GLOBALS['work'].'/output/'; }
function set_ng(...$args) { return ''; }
function set_ok(...$args) { return ''; }
function fnam_edit(...$args) { return 'audio'; }
function rf_set_genre(...$args) { return ''; }
function rf_check_double_rec(...$args) { return false; }
function rf_capacity_check(...$args) { return true; }
function rf_tf30_check() { return false; }
function rf_premium_mode(...$args) { return 0; }
function rf_premium_mode_r1(...$args) { return true; }
function rfriends_auth_radiko(...$args) { return $GLOBALS['scenario']==='auth_failed' ? null : 'offline-fixture'; }
function get_timefree_stream_url_tf30(...$args) { return $GLOBALS['scenario']==='hls_failed' ? '' : 'fixture.m3u8'; }
function rfgw_ffmpeg_opt(...$args) { return '-i %s'; }
function get_mktime($s) { return strtotime($s); }
function rf_touch($p) { touch($p); }
function fin_unlink($p) { if (file_exists($p)) unlink($p); }
function external_program($ignored) {
    if ($GLOBALS['scenario']==='download_failed') return 1;
    $duration=$GLOBALS['duration']-($GLOBALS['scenario']==='short' ? 30 : 0);
    $size=max(1,$duration)*8000;
    $header='RIFF'.pack('V',36+$size).'WAVEfmt '.pack('VvvVVvv',16,1,1,8000,8000,1,8).'data'.pack('V',$size);
    file_put_contents($GLOBALS['tmpdir'].'recording.wav',$header.str_repeat(chr(128),$size));
    return 0;
}
function get_mediainfo(...$args) { return $GLOBALS['duration']-($GLOBALS['scenario']==='short' ? 30 : 0); }
function rf_space_check(...$args) { return true; }
function set_tag_img(...$args) {} // Original title retained in structured manifest, never shell.
function rf_movefile($from,$to,...$args) {
    if ($GLOBALS['scenario']==='publish_failed' || file_exists($to)) return false;
    return rename($from,$to);
}
function rec_file_check(...$args) { return false; } // No deletion of other recordings.
function rftrans_job(...$args) { return true; } // No transfer, notification or hooks.
function rfgw_start_dontsleep(...$args) {}
