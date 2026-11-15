import subprocess
import unittest
from unittest.mock import patch, MagicMock


DF_OUTPUT = (
    "Images\t4.021GB (42%)\n"
    "Containers\t653.7MB (99%)\n"
    "Local Volumes\t4.821GB (23%)\n"
    "Build Cache\t6.906GB\n"
)


def _df_result(stdout=DF_OUTPUT, returncode=0):
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    return result


class TestDockerReclaimable(unittest.TestCase):
    def test_parses_df_output(self):
        from ozempic.cleaner import _docker_reclaimable

        with patch("ozempic.cleaner.subprocess.run", return_value=_df_result()):
            result = _docker_reclaimable()

        self.assertEqual(result["Images"], "4.021 GB")
        self.assertEqual(result["Containers"], "653.7 MB")
        self.assertEqual(result["Local Volumes"], "4.821 GB")
        self.assertEqual(result["Build Cache"], "6.906 GB")

    def test_missing_docker_cli_returns_none(self):
        from ozempic.cleaner import _docker_reclaimable

        with patch(
            "ozempic.cleaner.subprocess.run",
            side_effect=FileNotFoundError("docker not found"),
        ):
            self.assertIsNone(_docker_reclaimable())

    def test_daemon_down_returns_none(self):
        from ozempic.cleaner import _docker_reclaimable

        with patch(
            "ozempic.cleaner.subprocess.run",
            return_value=_df_result(stdout="", returncode=1),
        ):
            self.assertIsNone(_docker_reclaimable())


class TestCleanDocker(unittest.TestCase):
    def test_dry_run_reports_without_pruning(self):
        from ozempic.cleaner import _clean_docker

        with patch(
            "ozempic.cleaner.subprocess.run", return_value=_df_result()
        ) as mock_run:
            results = _clean_docker(dry_run=True)

        labels = [r["label"] for r in results]
        self.assertEqual(
            labels,
            ["Docker stopped containers", "Docker unused images", "Docker build cache"],
        )
        # Only the df call — no prune commands in dry run
        self.assertEqual(mock_run.call_count, 1)

    def test_real_run_invokes_prunes(self):
        from ozempic.cleaner import _clean_docker

        with patch(
            "ozempic.cleaner.subprocess.run", return_value=_df_result()
        ) as mock_run:
            results = _clean_docker(dry_run=False)

        commands = [call.args[0] for call in mock_run.call_args_list[1:]]
        self.assertIn(["docker", "container", "prune", "-f"], commands)
        self.assertIn(["docker", "image", "prune", "-af"], commands)
        self.assertIn(["docker", "builder", "prune", "-af"], commands)
        # Volumes are never pruned automatically
        for cmd in commands:
            self.assertNotIn("volume", cmd)
        self.assertEqual(len(results), 3)

    def test_zero_reclaimable_skipped(self):
        from ozempic.cleaner import _clean_docker

        df = _df_result(stdout="Images\t0B\nContainers\t0B\nBuild Cache\t0B\n")
        with patch("ozempic.cleaner.subprocess.run", return_value=df):
            self.assertEqual(_clean_docker(dry_run=True), [])

    def test_docker_unavailable_returns_empty(self):
        from ozempic.cleaner import _clean_docker

        with patch(
            "ozempic.cleaner.subprocess.run",
            side_effect=FileNotFoundError("docker not found"),
        ):
            self.assertEqual(_clean_docker(dry_run=False), [])


if __name__ == "__main__":
    unittest.main()
