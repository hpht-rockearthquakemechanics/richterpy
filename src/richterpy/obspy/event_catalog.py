"""Build ObsPy event catalog products."""

from richterpy.convert.events import convert_events, main, valid_experiment_code
from richterpy.io.esf import build_esf_catalog, build_esf_catalog_from_esfs

build_event_catalog = convert_events
build_event_catalog_from_esf = build_esf_catalog
build_event_catalog_from_esf_files = build_esf_catalog_from_esfs
