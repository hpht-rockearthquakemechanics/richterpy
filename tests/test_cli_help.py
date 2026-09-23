from __future__ import annotations

import subprocess
import sys
import unittest


class CLIHelpTests(unittest.TestCase):
    COMMAND_MODULES = {
        "richter-esf": "richterpy.io.esf",
        "richter-project-metadata": "richterpy.insite.project_metadata",
        "richter-event-waveforms": "richterpy.insite.event_waveforms",
        "richter-stationxml": "richterpy.convert.stations",
        "richter-quakeml": "richterpy.convert.events",
        "richter-esf-quakeml": "richterpy.convert.esf_quakeml",
        "richter-snuffler": "richterpy.convert.snuffler",
    }

    def test_console_command_modules_support_help(self):
        for command, module in self.COMMAND_MODULES.items():
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                output = result.stdout.lower()
                self.assertIn("usage:", output)
                self.assertIn("-h", output)


if __name__ == "__main__":
    unittest.main()
