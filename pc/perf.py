# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""`multiput --perf-test`: measure the round trip to the Pico over Wi-Fi and Bluetooth.

Each test acts like multiput does while playing: it keeps the link "in use" by sending
signed "nothing pressed" reports, so the Pico pauses the other link exactly as in real
use. Meanwhile it sends a HELLO every PROBE_INTERVAL_S and times the Pico's SYNC reply.
The Switch just sees an idle controller during the test.
"""

import statistics
import time

from controller import NEUTRAL_REPORT
from links import SerialLink, UdpLink, find_bt_port
from protocol import HELLO, SYNC_LEN, SYNC_MAGIC, Session

PROBES = 300               # per link: about 45 s
PROBE_INTERVAL_S = 0.15    # above the Pico's 100 ms SYNC rate limit, so every probe can be answered
PROBE_TIMEOUT_S = 0.5      # no reply by then counts as lost
KEEPALIVE_S = 0.05         # same cadence as multiput
HANDSHAKE_TIMEOUT_S = 15.0
LINK_SWITCH_WAIT_S = 3.0   # the Pico treats a link as idle 2 s after its last signed input


def measure(link, key, probes=PROBES, interval=PROBE_INTERVAL_S, timeout=PROBE_TIMEOUT_S, progress=None):
    """Round-trip times in ms and the number of lost probes, or None if the Pico never answered."""
    session = Session(link, key)
    deadline = time.monotonic() + HANDSHAKE_TIMEOUT_S
    while not session.ready:
        session.poll(time.monotonic())
        if time.monotonic() > deadline:
            return None
        time.sleep(0.005)
    nonce, rtts, lost, last_keepalive = session.nonce, [], 0, 0.0

    def keepalive(now):
        nonlocal last_keepalive
        if now - last_keepalive >= KEEPALIVE_S:
            session.send(NEUTRAL_REPORT)
            last_keepalive = now

    for i in range(probes):
        link.recv()  # drop anything left over
        rx, start, answered = b"", time.perf_counter(), False
        link.send(HELLO)
        while (now := time.perf_counter()) - start < timeout:
            rx += link.recv()
            at = rx.find(SYNC_MAGIC)
            if at >= 0 and len(rx) >= at + SYNC_LEN:
                if rx[at + 2:at + 10] != nonce:
                    raise SystemExit("The Pico restarted during the test; run it again.")
                rtts.append((now - start) * 1000)
                answered = True
                break
            keepalive(now)
            time.sleep(0.0005)
        lost += not answered
        while (now := time.perf_counter()) - start < interval:
            keepalive(now)
            time.sleep(0.001)
        if progress:
            progress(i + 1, probes)
    session.send(NEUTRAL_REPORT)
    return rtts, lost


def summarize(rtts, lost):
    """Stats for one link, as a dict of display values."""
    s = sorted(rtts)
    pct = lambda p: s[min(len(s) - 1, int(p / 100 * len(s)))]
    sent = len(s) + lost
    if not s:
        return {"replies": f"0/{sent}", "lost": str(lost)}
    return {"replies": f"{len(s)}/{sent}", "lost": str(lost), "min": f"{s[0]:.1f}",
            "median": f"{statistics.median(s):.1f}", "p90": f"{pct(90):.1f}", "p99": f"{pct(99):.1f}",
            "max": f"{s[-1]:.1f}", "over20": str(sum(r > 20 for r in s)),
            "oneway": f"~{statistics.median(s) / 2:.1f}"}


COLUMNS = [("Link", "link"), ("Replies", "replies"), ("Lost", "lost"), ("Min", "min"), ("Median", "median"),
           ("p90", "p90"), ("p99", "p99"), ("Max", "max"), (">20 ms", "over20"), ("One way", "oneway")]


def table(rows):
    widths = [max(len(title), *(len(r.get(key, "-")) for r in rows)) for title, key in COLUMNS]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths))
    out = [line([t for t, _ in COLUMNS]), line(["-" * w for w in widths])]
    out += [line([r.get(key, "-") for _, key in COLUMNS]) for r in rows]
    return "\n".join(out)


def run_perf_test(args, saved, key):
    print("multiput performance test\n")
    print("Measures the round trip PC -> Pico -> PC on each link, the way multiput uses it.")
    print(f"About {PROBES * PROBE_INTERVAL_S:.0f} s per link. The Switch sees an idle controller meanwhile.\n")
    rows = []

    def progress(done, total):
        print(f"\r  {done}/{total}", end="", flush=True)

    if saved.get("pico_wifi") is False:
        print("Wi-Fi: skipped (the Pico was set up without Wi-Fi).")
    else:
        print("Wi-Fi:")
        result = measure(UdpLink(args.host or saved.get("host", "multiput.local")), key, progress=progress)
        print()
        rows.append({"link": "Wi-Fi", **(summarize(*result) if result else {"replies": "no answer"})})

    port = args.bt or find_bt_port() or saved.get("port")
    if not port:
        print("Bluetooth: skipped (pair 'multiput' in Windows first; see the README).")
    else:
        if rows:
            time.sleep(LINK_SWITCH_WAIT_S)  # let the Pico notice Wi-Fi went idle and listen on Bluetooth
        print(f"Bluetooth ({port}):")
        link = SerialLink(port)
        try:
            result = measure(link, key, progress=progress)
        finally:
            link.ser.close()
        print()
        rows.append({"link": "Bluetooth", **(summarize(*result) if result else {"replies": "no answer"})})

    print("\nRound trip PC -> Pico -> PC, in ms. A button press only travels one way (PC -> Pico),")
    print("so the delay it adds is about half the round trip (\"One way\", from the median).\n")
    print(table(rows))
