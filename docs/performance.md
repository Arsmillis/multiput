# Performance test

multiput can measure how quickly the PC reaches the Pico over Wi‑Fi and Bluetooth, on your own hardware and network.

## Running it
1. **Close multiput.** The test needs the Pico to itself, and multiput refuses to run twice.
2. Make sure the Pico is powered: in the Switch dock, or plugged into the PC. For the Bluetooth half, it must be paired with Windows (see the README's [Wi‑Fi or Bluetooth](../README.md#wi-fi-or-bluetooth) section). Otherwise that half is skipped.
3. Start **Start menu → multiput performance test**. From a terminal, run `multiput --perf-test`; from a source checkout, run `py pc\multiput.py --perf-test` (Bluetooth needs pyserial).
4. Wait about 1.5 minutes: around 45 s per link, with a counter showing progress. The Switch sees an idle controller during the test, so don't play meanwhile.

It prints a table like the one under [Findings](#findings). `--host` (positional, e.g. `multiput --perf-test 192.168.1.50`) and `--bt COM5` override the link details, as for a normal run.

## What it measures
For each link in turn, the test acts like multiput while playing: it keeps sending signed "nothing pressed" reports every 50 ms. That makes the link count as **in use**, so the Pico pauses the other link exactly as it would in real use. Meanwhile it sends a HELLO every 150 ms and times the Pico's reply: the **round trip** PC → Pico → PC.

- **Probes:** 300 per link. They're spaced above the Pico's 100 ms reply limit, so an unanswered probe is a genuinely lost message.
- **One way:** a button press only travels PC → Pico, so the delay it adds is roughly half the round trip. The "One way" column is half the median. Treat it as an estimate: radio links aren't always symmetric.
- **What's not included:** the controller → PC hop (1–8 ms, which PC games pay too) and the Switch reading the input on its next frame (0–16.7 ms, which happens with any controller). See [How it works](how-it-works.md#end-to-end-from-your-seat).

### Reading the table
| Column | Meaning |
|---|---|
| Replies, Lost | Probes answered / sent, and probes with no reply within 0.5 s |
| Min, Median, Max | Fastest, typical and slowest round trip, in ms |
| p90, p99 | 90% / 99% of round trips were at or below this |
| >20 ms | How many round trips took over 20 ms. One way, that's roughly 10 ms, over half a Switch frame |
| One way | Estimated delay added to each button press (half the median) |

## Findings
Run on 2026-11-15:
- **Hardware and network:** the Pico W was running the combined Wi‑Fi + Bluetooth firmware (arduino-pico core 6.3.2) and was in the Switch 2 dock. The PC was on Windows. The Wi‑Fi was a home 2.4 GHz network.
- **Method:** 300 probes per link.

| Link | Replies | Lost | Min | Median | p90 | p99 | Max | >20 ms | One way |
|---|---|---|---|---|---|---|---|---|---|
| Wi‑Fi | 300/300 | 0 | 4.0 | 6.2 | 8.1 | 12.6 | 30.1 | 2 | ~3.1 |
| Bluetooth | 299/300 | 1 | 4.9 | 7.1 | 21.0 | 45.5 | 67.7 | 32 | ~3.5 |

All times are round trips in ms.

**What this shows:**
- **Typical speed is almost the same.** A median of 6.2 ms against 7.1 ms means about 3 ms against 3.5 ms added per button press. Both are well within one Switch frame (16.7 ms).
- **Wi‑Fi is steady; Bluetooth has spikes.**
  - On Wi‑Fi, 99% of round trips took 12.6 ms or less, and only 2 of 300 went over 20 ms.
  - On Bluetooth, about 1 in 10 (32 of 299) went over 20 ms, and the slowest 1% took 45 ms or more. That's over 20 ms one way, more than a full frame.
  - In fast games you could feel this as an occasional late input.
- **Losses:** none on Wi‑Fi, and 1 in 300 on Bluetooth. Lost input isn't missed for long: multiput resends the current state at least every 50 ms.
- **Pausing the idle link costs nothing on Wi‑Fi.** An earlier run, with multiput's own traffic and 400 probes on Wi‑Fi, gave a median of 5.7 ms and a p99 of 11.9 ms, consistent with this run. The older Wi‑Fi-only firmware measured 5.4 ms in a single sample.

**Recommendation:**
- **Use Wi‑Fi for play,** especially action games.
- **Bluetooth is fine** where an occasional 20–45 ms hiccup doesn't matter: menus, turn-based games, or when no shared Wi‑Fi network is available.

Results depend on your network and radio surroundings, so run the test on your own setup. For example, a busy 2.4 GHz network, or the PC's own Bluetooth also serving the Xbox controller, can change the Bluetooth numbers.
