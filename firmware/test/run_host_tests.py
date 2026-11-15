"""Run firmware logic tests without a board: python firmware/test/run_host_tests.py."""
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    compiler = shutil.which(os.environ.get("CXX", "g++"))
    if compiler is None:
        raise SystemExit("Install g++ or set CXX to a C++ compiler on PATH.")
    firmware = Path(__file__).resolve().parents[1]
    build_dir = firmware / ".pio" / "host-tests"
    build_dir.mkdir(parents=True, exist_ok=True)
    binary = build_dir / ("station_tests.exe" if os.name == "nt" else "station_tests")
    subprocess.run(
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-I", str(firmware / "include"), str(firmware / "test/test_station_logic.cpp"),
         "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
