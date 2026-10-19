from types import SimpleNamespace

from openpilot.selfdrive.mapd.mapd_config import (ManualRefresh, format_download_status, MANUAL_RESEND_PERIOD,
                                                  MANUAL_CONFIRM_TIMEOUT)


def progress(active, total=0, done=0):
  return SimpleNamespace(active=active, totalFiles=total, downloadedFiles=done)


class TestManualRefresh:
  def test_idle_does_nothing(self):
    m = ManualRefresh()
    for t in range(50):
      assert m.step(t * 0.1, False, False) == (False, False, False)

  def test_resends_until_mapd_reports_active(self):
    m = ManualRefresh()
    sends = 0
    t = 0.
    # mapd ignores the first ~2 s of sends, then starts the download
    while t < 2.0:
      send, done, failed = m.step(t, True, False)
      assert not done and not failed
      sends += send
      t += 0.1
    assert 5 <= sends <= 8          # about one resend per MANUAL_RESEND_PERIOD, not one per tick
    assert m.step(t, True, True) == (False, True, False)
    # after done, the request flag is cleared by the caller; further ticks stay quiet
    assert m.step(t + 0.1, False, True) == (False, False, False)

  def test_gives_up_when_mapd_never_answers(self):
    m = ManualRefresh()
    t = 0.
    result = None
    while t < MANUAL_CONFIRM_TIMEOUT + 2:
      send, done, failed = m.step(t, True, False)
      assert not done
      if failed:
        result = t
        break
      t += 0.1
    assert result is not None and MANUAL_CONFIRM_TIMEOUT <= result <= MANUAL_CONFIRM_TIMEOUT + 0.2
    # the caller clears the flag, so a new press starts a fresh attempt
    assert m.step(result + 1, True, False)[0] is True

  def test_download_already_running_is_done_without_sending(self):
    m = ManualRefresh()
    assert m.step(0., True, True) == (False, True, False)

  def test_first_send_is_immediate(self):
    m = ManualRefresh()
    assert m.step(100., True, False) == (True, False, False)
    assert m.step(100. + MANUAL_RESEND_PERIOD / 2, True, False) == (False, False, False)


class TestStatusText:
  def test_idle_is_empty(self):
    assert format_download_status(progress(False)) == ""
    assert format_download_status(progress(False, 196, 196)) == ""

  def test_progress_text(self):
    assert format_download_status(progress(True, 196, 45)) == "download 45/196"
    assert format_download_status(progress(True)) == "downloading"
