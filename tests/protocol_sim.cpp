// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Desktop build of the Pico protocol code, driven by tests/test_protocol.py over stdin:
//   "init <keyhex> <allowUnsigned> <r1> <r2>" | "feed <hex>" (appended to a byte stream)
//   "fwversion <x.y.z | ->" (what VERSION requests are answered with; "-" = never answer, like 0.1.0)
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>
#include "protocol.h"
using namespace std;

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
      stream.clear();
      cout << "ok\n";
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
