"""ObsPy waveform stream helpers."""

from richterpy.io.atf import build_atf_stream
from richterpy.io.esf import build_esf_stream

build_waveform_stream = build_esf_stream
build_atf_waveform_stream = build_atf_stream
