// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Desktop build of the Pico protocol code, driven by tests/test_protocol.py over stdin:
//   "init <keyhex> <allowUnsigned> <r1> <r2>" | "feed <hex>" (appended to a byte stream)
//   "fwversion <x.y.z | ->" (what VERSION requests are answered with; "-" = never answer, like 0.1.0)
//   "time <ms>" (the clock ota.h sees) | "storagefail <0|1>" | "otastate" (what the fake storage got)
//   "choose <builtin> <saved> <savedFrom>" -> settings.h's choose_settings(); builtin and savedFrom are
//     blank|A|B (built-in blocks), saved is none|garbage|X (X: a configured settings file)
//   "blank <hex>" -> ota.h's bytes_blank(): 1 if all 0x00 or all 0xFF
//   "keystore <hex> <bankStart 0|1>" -> ota.h's keystore_chunk_empty()
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>
#include "protocol.h"
#include "settings.h"
using namespace std;

// In-memory stand-in for the sketch's flash storage (ota.h's g_ota).
static uint32_t simTime = 0, simSize = 0;
static vector<uint8_t> simImage;
static bool simFinished = false, simFail = false;
static int simAborts = 0, simRestarts = 0;
static string simSsid = "-", simPass = "-";
static bool simBegin(uint32_t size) { simSize = size; simImage.clear(); simFinished = false; return !simFail; }
static bool simWrite(const uint8_t *d, size_t n) { simImage.insert(simImage.end(), d, d + n); return !simFail; }
static bool simFinish() { simFinished = simImage.size() == simSize; return simFinished && !simFail; }
static void simAbort() { simAborts++; simImage.clear(); }
static bool simSaveWifi(const char *ssid, const char *pass) { simSsid = ssid; simPass = pass; return !simFail; }
static void simRestartSoon() { simRestarts++; }
static uint32_t simNow() { return simTime; }

static vector<uint8_t> unhex(const string &s) {
  vector<uint8_t> v;
  for (size_t i = 0; i + 1 < s.size(); i += 2) v.push_back(stoi(s.substr(i, 2), nullptr, 16));
  return v;
}
static string hex(const uint8_t *p, size_t n) {
  string s;
  char b[3];
  for (size_t i = 0; i < n; i++) { snprintf(b, 3, "%02x", p[i]); s += b; }
  return s;
}

int main() {
  string cmd, fwversion = "-";
  vector<uint8_t> stream;
  while (cin >> cmd) {
    if (cmd == "init") {
      string k;
      int allow;
      uint32_t r1, r2;
      cin >> k >> allow >> r1 >> r2;
      protocol_init(unhex(k).data(), allow, r1, r2);
      ota_init(unhex(k).data());
      g_ota = {simBegin, simWrite, simFinish, simAbort, simSaveWifi, simRestartSoon, simNow};
      stream.clear();
      cout << "ok\n";
    } else if (cmd == "time") {
      cin >> simTime;
      ota_poll();
      cout << "ok\n";
    } else if (cmd == "storagefail") {
      cin >> simFail;
      cout << "ok\n";
    } else if (cmd == "otastate") {
      cout << "size=" << simSize << " written=" << simImage.size() << " finished=" << simFinished
           << " aborts=" << simAborts << " restarts=" << simRestarts << " wifi=" << (simSsid.empty() ? "<off>" : simSsid)
           << "/" << (simPass.empty() ? "<none>" : simPass) << " image=" << hex(simImage.data(), simImage.size()) << "\n";
    } else if (cmd == "blank") {
      string h;
      cin >> h;
      auto b = unhex(h);
      cout << bytes_blank(b.data(), b.size()) << "\n";
    } else if (cmd == "keystore") {
      string h;
      int start;
      cin >> h >> start;
      auto b = unhex(h);
      cout << keystore_chunk_empty(b.data(), b.size(), start) << "\n";
    } else if (cmd == "choose") {
      string b, s, from;
      cin >> b >> s >> from;
      auto block = [](const string &which) {
        Settings x;
        memset(&x, 0, sizeof x);
        if (which != "blank") { x.configured = 1; x.ssid[0] = which[0]; }
        return x;
      };
      Settings builtin = block(b);
      SavedSettings saved;
      memset(&saved, 0, sizeof saved);
      if (s == "X") { saved.s.configured = 1; saved.s.ssid[0] = 'X'; }
      saved.builtinHash = settings_hash(block(from));
      SettingsChoice c = choose_settings(builtin, s == "none" ? nullptr : &saved);
      cout << (c == USE_BUILTIN ? "BUILTIN" : c == USE_SAVED ? "SAVED" : "NONE") << "\n";
    } else if (cmd == "fwversion") {
      cin >> fwversion;
      cout << "ok\n";
    } else if (cmd == "feed") {
      string h;
      cin >> h;
      auto b = unhex(h);
      stream.insert(stream.end(), b.begin(), b.end());
      size_t off = 0;
      string out;
      while (off < stream.size()) {
        Frame f = parse_frame(stream.data() + off, stream.size() - off);
        if (!f.used) break;
        off += f.used;
        if (f.accepted) out += "A:" + hex((uint8_t *)&g_report, 8) + " ";
        if (f.wantSync) { uint8_t s[SYNC_LEN]; build_sync(s); out += "S:" + hex(s, SYNC_LEN) + " "; }
        if (f.replyLen) out += "R:" + hex(f.reply, f.replyLen) + " ";
        if (f.wantStatus) out += "G:" + hex((const uint8_t *)"MG\x03sim", 6) + " ";
        if (f.wantVersion && fwversion != "-") {
          uint8_t v[3 + VERSION_MAX];
          size_t n = build_version(v, fwversion.c_str());
          out += "V:" + hex(v, n) + " ";
        }
      }
      stream.erase(stream.begin(), stream.begin() + off);
      cout << (out.empty() ? "-" : out) << "\n";
    }
    cout.flush();
  }
}
