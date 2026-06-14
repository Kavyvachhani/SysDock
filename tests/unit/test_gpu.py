"""GPU backend tests — parsers fixture-tested; dispatcher never errors."""

from __future__ import annotations

from sysdock.core.gpu import GpuCollector, amd, apple, intel, nvidia
from sysdock.core.gpu.schema import GpuSample

# ── AMD (rocm-smi --json) ──────────────────────────────────────────────────────

ROCM_JSON = """{
  "card0": {
    "GPU use (%)": "45",
    "GPU Memory Allocated (VRAM%)": "12",
    "VRAM Total Memory (B)": "25753026560",
    "VRAM Total Used Memory (B)": "2147483648",
    "Temperature (Sensor edge) (C)": "52.0",
    "Average Graphics Package Power (W)": "35.0",
    "Card Series": "Radeon RX 7900 XTX"
  }
}"""


def test_parse_rocm_json():
    devices = amd.parse_rocm_json(ROCM_JSON)
    assert len(devices) == 1
    d = devices[0]
    assert d.vendor == "amd"
    assert "Radeon" in d.name
    assert d.util_percent == 45.0
    assert d.mem_total == 25753026560
    assert d.mem_used == 2147483648
    assert d.temp_c == 52.0
    assert d.power_w == 35.0
    assert d.mem_percent is not None


def test_parse_rocm_garbage():
    assert amd.parse_rocm_json("not json") == []
    assert amd.parse_rocm_json("[]") == []


# ── Intel (intel_gpu_top -J) ───────────────────────────────────────────────────

INTEL_JSON = """[
{
  "engines": {
    "Render/3D/0": {"busy": 73.2, "unit": "%"},
    "Blitter/0": {"busy": 0.0, "unit": "%"},
    "Video/0": {"busy": 5.0, "unit": "%"}
  },
  "power": {"GPU": 4.2, "Package": 9.0}
}
"""


def test_parse_intel_json():
    devices = intel.parse_intel_json(INTEL_JSON)
    assert len(devices) == 1
    d = devices[0]
    assert d.vendor == "intel"
    assert d.util_percent == 73.2  # busiest engine
    assert d.power_w == 4.2


def test_intel_first_json_object_extraction():
    assert intel._first_json_object('garbage {"a":1} trailing') == '{"a":1}'
    assert intel._first_json_object("no object here") is None


def test_parse_intel_garbage():
    assert intel.parse_intel_json("nonsense") == []


# ── Apple (system_profiler) ────────────────────────────────────────────────────

SP_DISPLAYS = """Graphics/Displays:

    Apple M2:

      Chipset Model: Apple M2
      Type: GPU
      Bus: Built-In
      Total Number of Cores: 10
      Vendor: Apple (0x106b)
      Metal Support: Metal 3
"""


def test_parse_apple_displays():
    devices = apple.parse_displays(SP_DISPLAYS, mem_total=17179869184)
    assert len(devices) == 1
    d = devices[0]
    assert d.vendor == "apple"
    assert "Apple M2" in d.name
    assert "10-core" in d.name
    assert d.mem_total == 17179869184


def test_parse_apple_no_gpu():
    assert apple.parse_displays("Graphics/Displays:\n\n  No GPU here\n") == []


# ── NVIDIA + dispatcher ────────────────────────────────────────────────────────


def test_nvidia_available_is_bool():
    assert isinstance(nvidia.available(), bool)


def test_nvidia_collect_without_lib_is_empty():
    # pynvml is not installed in the test env -> clean empty, no error.
    if not nvidia.available():
        assert nvidia.collect() == []


def test_collector_never_raises_and_caches():
    c = GpuCollector(ttl=60.0)
    sample = c.collect()
    assert isinstance(sample, GpuSample)
    # Cached on second call.
    assert c.collect() is sample
    # Either devices were found, or it's cleanly unavailable with a reason.
    assert sample.available == bool(sample.devices)
    if not sample.available:
        assert sample.reason


def test_collector_with_no_backends(monkeypatch):
    """With every backend returning nothing, the panel is cleanly hidden."""
    import sysdock.core.gpu as gpu_mod

    monkeypatch.setattr(gpu_mod, "_BACKENDS", [("none", lambda: [])])
    sample = GpuCollector(ttl=0.0).collect()
    assert sample.available is False
    assert sample.devices == []
    assert sample.reason


def test_collector_survives_a_broken_backend(monkeypatch):
    import sysdock.core.gpu as gpu_mod

    def boom() -> list:
        raise RuntimeError("driver exploded")

    monkeypatch.setattr(gpu_mod, "_BACKENDS", [("boom", boom)])
    # Must not raise; degrades to unavailable.
    sample = GpuCollector(ttl=0.0).collect()
    assert sample.available is False
