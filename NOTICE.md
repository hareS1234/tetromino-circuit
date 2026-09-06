# Third-party notices and attribution

* The four-feature heuristic (lines, aggregate height, holes, bumpiness) and its starting
  coefficients (76, 51, 36, 18 as integer magnitudes of 0.760666, 0.510066, 0.35663, 0.184483) follow
  Yiyuan Lee, *Tetris AI – The (Near) Perfect Bot* (2013). The coefficients were not tuned here; the
  quantized profiles P5–P7 are derived from them deterministically (`model/numeric.py`).
* Tools: YosysHQ OSS CAD Suite (Yosys, nextpnr-ecp5, Verilator, SymbiYosys, boolector), cocotb,
  Python packages listed in `requirements.lock`. Each is used under its own licence; nothing from
  them is redistributed in this repository (the suite is downloaded by `scripts/bootstrap.sh` and
  verified against `toolchains/oss_cad_suite.lock.json`).
This repository's own code and documents are released under the MIT License (`LICENSE`).
